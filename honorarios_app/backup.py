"""Private local backups: preserve duplicate safety and interrupted draft recovery.

Recovery capsules contain only the original reviewed files of pending attempts.
They are not a document archive, credentials, or transferable review authority.
"""
from __future__ import annotations

import base64
import binascii
import copy
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
from typing import Any

from scripts.generate_pdf import IntakeError
from scripts.request_identity import request_identity_key
from scripts.state_store import state_file_lock
from .gmail_attempts import attempt_lock

TERMINAL = {"recorded", "not_created", "confirmed_not_created"}
STATES = TERMINAL | {"started", "uncertain", "created_unrecorded"}
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_CAPSULE_BYTES = 100 * 1024 * 1024
MAX_ARTIFACTS = 256
ATTACHMENT_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


@contextmanager
def runtime_lock(draft_log: Path):
    """Same order as create/recover -> record CLI; never acquire in reverse."""
    with attempt_lock(draft_log), state_file_lock(draft_log.with_name(".gmail-history.lock")):
        yield


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encoded_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def validate_attempts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise IntakeError("Backup Gmail attempts must be a list.")
    seen = set()
    for row in value:
        if (not isinstance(row, dict) or not isinstance(row.get("attempt_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", row["attempt_id"])
                or row["attempt_id"] in seen or row.get("state") not in STATES
                or not isinstance(row.get("requests"), list) or not row["requests"]
                or any(not isinstance(item, dict) or not all(request_identity_key(item)[:2]) for item in row["requests"])
                or not isinstance(row.get("payload"), str) or not row["payload"]
                or not isinstance(row.get("target"), dict) or not isinstance(row.get("prepared_review"), dict)
                or not isinstance(row.get("gmail_create_draft_args"), dict)):
            raise IntakeError("Backup contains an invalid or repeated Gmail attempt.")
        result = row.get("gmail_result") or {}
        if not isinstance(result, dict) or (result and (not result.get("draft_id") or not result.get("message_id"))):
            raise IntakeError("Backup Gmail attempt has incomplete returned draft IDs.")
        if row["state"] in {"recorded", "created_unrecorded"} and not result:
            raise IntakeError("Backup recorded Gmail attempt is missing returned draft IDs.")
        seen.add(row["attempt_id"])
    return value


def artifact_bindings(attempt: dict[str, Any]) -> dict[str, tuple[str, str]]:
    target = attempt["target"]
    result: dict[str, tuple[str, str]] = {}
    def add(path, sha, role):
        if not isinstance(path, str) or not path or not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise IntakeError("Backup attempt has an invalid original artifact binding.")
        binding = (sha, role)
        if path in result and result[path] != binding:
            raise IntakeError("Backup attempt has conflicting original artifact bindings.")
        result[path] = binding
    add(attempt["payload"], target.get("draft_payload_sha256"), "payload")
    for path, sha in target.get("child_payload_sha256", {}).items():
        add(path, sha, "child_payload")
    for path, sha in target.get("attachment_sha256", {}).items():
        add(path, sha, "attachment")
    return result


def export_recovery_capsules(attempts: list[dict[str, Any]], paths) -> dict[str, Any]:
    roots = [getattr(paths, key).resolve() for key in ("draft_output_dir", "output_dir", "packet_output_dir", "source_upload_dir")]
    entries = []
    total = 0
    count = 0
    for attempt in validate_attempts(attempts):
        if attempt["state"] in TERMINAL:
            continue
        artifacts, omitted = [], []
        for raw_path, (sha, role) in artifact_bindings(attempt).items():
            path = Path(raw_path).resolve()
            expected_suffixes = {".json"} if role != "attachment" else ATTACHMENT_SUFFIXES
            # Resolve symlinks before checking roots. A corrupted journal must not
            # turn a private backup into an arbitrary local file reader.
            if not any(path.is_relative_to(root) for root in roots) or path.suffix.lower() not in expected_suffixes:
                omitted.append({"path": raw_path, "reason": "outside supported app-owned recovery files"})
                continue
            try:
                if path.stat().st_size > MAX_ARTIFACT_BYTES or total + path.stat().st_size > MAX_CAPSULE_BYTES or count >= MAX_ARTIFACTS:
                    raise ValueError("recovery size limit exceeded")
                with path.open("rb") as handle:
                    data = handle.read(MAX_ARTIFACT_BYTES + 1)
                if len(data) > MAX_ARTIFACT_BYTES or digest(data) != sha:
                    raise ValueError("original reviewed file is changed or too large")
                total += len(data)
                count += 1
                artifacts.append({"path": raw_path, "sha256": sha, "role": role, "data_base64": base64.b64encode(data).decode("ascii")})
            except (OSError, ValueError) as exc:
                omitted.append({"path": raw_path, "reason": str(exc)})
        entries.append({"attempt_id": attempt["attempt_id"], "artifacts": artifacts, "omitted": omitted})
    return {"schema_version": 1, "entries": entries, "scope": "pending_attempt_recovery_only"}


def validate_capsules(capsules: Any, attempts: list[dict[str, Any]]) -> dict[str, dict[str, bytes]]:
    if capsules is None:
        return {}
    if not isinstance(capsules, dict) or capsules.get("schema_version") != 1 or not isinstance(capsules.get("entries"), list):
        raise IntakeError("Backup recovery capsule format is invalid.")
    known = {row["attempt_id"]: row for row in validate_attempts(attempts)}
    result = {}
    total = count = 0
    for entry in capsules["entries"]:
        if not isinstance(entry, dict) or entry.get("attempt_id") not in known or entry["attempt_id"] in result or not isinstance(entry.get("artifacts"), list):
            raise IntakeError("Backup contains an unknown or repeated recovery capsule.")
        attempt = known[entry["attempt_id"]]
        if attempt["state"] in TERMINAL:
            raise IntakeError("Backup recovery files are only supported for pending attempts.")
        bindings = artifact_bindings(attempt)
        files = {}
        for item in entry["artifacts"]:
            if not isinstance(item, dict) or item.get("path") not in bindings or item["path"] in files:
                raise IntakeError("Backup contains an unknown or repeated recovery artifact.")
            raw = item["path"]
            windows = PureWindowsPath(raw)
            posix = Path(raw)
            if ".." in windows.parts or ".." in posix.parts or not (windows.is_absolute() or posix.is_absolute()):
                raise IntakeError("Backup recovery artifact path is invalid.")
            if (not windows.name or windows.is_reserved() or re.search(r'[<>:"/\\|?*\x00-\x1f]', windows.name)
                    or windows.name.rstrip(". ") != windows.name):
                raise IntakeError("Backup recovery artifact filename is invalid.")
            sha, role = bindings[raw]
            suffix = windows.suffix.lower()
            if item.get("sha256") != sha or item.get("role") != role or suffix not in ({".json"} if role != "attachment" else ATTACHMENT_SUFFIXES):
                raise IntakeError("Backup recovery artifact role or hash binding is invalid.")
            encoded = item.get("data_base64")
            if not isinstance(encoded, str) or len(encoded) > (MAX_ARTIFACT_BYTES + 2) // 3 * 4:
                raise IntakeError("Backup recovery artifact exceeds the size limit.")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise IntakeError("Backup recovery artifact has invalid base64 data.") from exc
            total += len(data)
            count += 1
            if total > MAX_CAPSULE_BYTES or count > MAX_ARTIFACTS or len(data) > MAX_ARTIFACT_BYTES or digest(data) != sha:
                raise IntakeError("Backup recovery artifact bytes do not match their hash or size limit.")
            if role != "attachment":
                try:
                    payload = json.loads(data)
                except (UnicodeError, ValueError) as exc:
                    raise IntakeError("Backup recovery payload is not valid JSON.") from exc
                if not isinstance(payload, dict) or payload.get("draft_only") is not True or payload.get("send_allowed") is not False:
                    raise IntakeError("Backup recovery payload is not draft-only.")
                attachments = payload.get("attachment_files")
                args = payload.get("gmail_create_draft_args")
                if (not isinstance(attachments, list) or not attachments or not isinstance(args, dict)
                        or args.get("attachment_files") != attachments
                        or any(not isinstance(path, str) or path not in bindings or bindings[path][1] != "attachment" for path in attachments)):
                    raise IntakeError("Backup recovery payload references an unbound attachment.")
                child_paths = payload.get("child_payload_paths") or []
                if (not isinstance(child_paths, list)
                        or any(not isinstance(path, str) or path not in bindings or bindings[path][1] != "child_payload" for path in child_paths)):
                    raise IntakeError("Backup recovery payload references an unbound child payload.")
                if role == "payload":
                    if (_identities({"requests": attempt["requests"]}) != _identities(payload)
                            or args != attempt["gmail_create_draft_args"]):
                        raise IntakeError("Backup recovery payload conflicts with the attempted requests or reviewed email.")
            files[raw] = data
        result[entry["attempt_id"]] = files
    return result


def _identities(row):
    return sorted(request_identity_key(item) for item in row.get("requests") or row.get("underlying_requests") or [row])


def merge_attempts(local: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = {row["attempt_id"]: copy.deepcopy(row) for row in validate_attempts(local)}
    for row in validate_attempts(incoming):
        old = result.get(row["attempt_id"])
        if old:
            a, b = old.get("gmail_result") or {}, row.get("gmail_result") or {}
            old_target = old.get("backup_original_target", old["target"])
            new_target = row.get("backup_original_target", row["target"])
            if (_identities(old) != _identities(row) or any(a.get(k) and b.get(k) and a[k] != b[k] for k in ("draft_id", "message_id"))
                    or old_target != new_target
                    or any(old["gmail_create_draft_args"].get(k) != row["gmail_create_draft_args"].get(k) for k in ("to", "subject", "body"))):
                raise IntakeError("Backup conflicts with the original identity or returned IDs of a local Gmail attempt.")
            # A backup cannot clear a locally unresolved reservation. Conversely,
            # importing an unresolved reservation must not lose that evidence.
            if old["state"] == "recorded":
                # The same immutable attempt is already positively recorded;
                # an old uncertain backup cannot reopen that completed work.
                selected = old
            elif old["state"] not in TERMINAL:
                selected = old
            elif row["state"] not in TERMINAL:
                selected = copy.deepcopy(row)
            else:
                selected = old
            if a or b:
                selected["gmail_result"] = copy.deepcopy(a or b)
                if selected["state"] not in TERMINAL:
                    selected["state"] = "created_unrecorded"
            result[row["attempt_id"]] = selected
        else:
            result[row["attempt_id"]] = copy.deepcopy(row)
    return list(result.values())


def merge_history(local: list, incoming: list, *, duplicate: bool) -> list:
    result = {}
    for row in [*local, *incoming]:
        if (not isinstance(row, dict) or not all(request_identity_key(row)[:2])
                or row.get("status") not in {None, "", "active", "drafted", "sent", "superseded", "trashed", "not_found"}
                or (row.get("underlying_requests") is not None and (not isinstance(row["underlying_requests"], list)
                    or any(not isinstance(item, dict) or not all(request_identity_key(item)[:2]) for item in row["underlying_requests"])))):
            raise IntakeError("Backup contains invalid draft or duplicate history.")
        stamp = row.get("updated_at") or row.get("drafted_at") or ""
        if stamp:
            try:
                if not isinstance(stamp, str) or datetime.fromisoformat(stamp).tzinfo is None:
                    raise ValueError("missing timezone")
            except ValueError as exc:
                raise IntakeError("Backup history has an invalid update timestamp.") from exc
        draft = str(row.get("draft_id") or "")
        key = (draft, request_identity_key(row)) if duplicate or not draft else draft
        old = result.get(key)
        if old:
            if (_identities(old) != _identities(row) or any(old.get(k) and row.get(k) and old[k] != row[k] for k in ("message_id", "pdf_sha256", "recipient", "recipient_email", "email_group_id"))):
                raise IntakeError("Backup contains conflicting draft identities or attachment history. Reconcile it before restoring.")
            old_status = old.get("status") or "sent"
            new_status = row.get("status") or "sent"
            # Prefer explicitly newer local evidence; missing/equal timestamps
            # cannot authorize retirement or resurrection of a draft.
            old_time = str(old.get("updated_at") or old.get("drafted_at") or "")
            new_time = str(row.get("updated_at") or row.get("drafted_at") or "")
            if old_status != new_status and (not old_time or not new_time or old_time == new_time):
                raise IntakeError("Backup draft status conflicts with local history without a clear newer update. Reconcile it before restoring.")
            newer = new_time and (not old_time or datetime.fromisoformat(new_time) > datetime.fromisoformat(old_time))
            if newer and old_status != new_status and (old_status == "sent" or new_status not in {"active", "drafted", "sent"}):
                raise IntakeError("Backup cannot retire an existing local draft or undo sent history. Reconcile that status locally first.")
            if newer:
                result[key] = copy.deepcopy(row)
        else:
            result[key] = copy.deepcopy(row)
    return list(result.values())


def rebase_value(value: Any, mapping: dict[str, str], hashes: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [rebase_value(item, mapping, hashes) for item in value]
    if not isinstance(value, dict):
        return value
    result = {mapping.get(key, key): rebase_value(item, mapping, hashes) for key, item in value.items()}
    for key in ("draft_payload", "pdf"):
        if result.get(key) in hashes and key + "_sha256" in result:
            result[key + "_sha256"] = hashes[result[key]]
    for key in ("child_payload_sha256", "attachment_sha256"):
        if isinstance(result.get(key), dict):
            result[key] = {path: hashes.get(path, sha) for path, sha in result[key].items()}
    return result


def restore_capsules(attempts: list[dict[str, Any]], files_by_id: dict[str, dict[str, bytes]], paths) -> tuple[list, dict, dict]:
    """Materialize only complete pending snapshots; originals are never overwritten."""
    result = copy.deepcopy(attempts)
    all_mapping, all_hashes = {}, {}
    root = (paths.draft_output_dir / "restored-attempts").resolve()
    if not root.is_relative_to(paths.draft_output_dir.resolve()):
        raise IntakeError("The local recovery folder points outside the app output folder.")
    for attempt in result:
        attempt["backup_original_review_fingerprint"] = attempt.get("backup_original_review_fingerprint", attempt["prepared_review"].get("review_fingerprint", ""))
        attempt["prepared_review"] = {key: value for key, value in attempt["prepared_review"].items()
                                     if key not in {"token", "fingerprint", "manifest_sha256", "prepared_review_token", "review_fingerprint"}}
        files = files_by_id.get(attempt["attempt_id"], {})
        if attempt["state"] in TERMINAL:
            continue
        bindings = artifact_bindings(attempt)
        if set(files) != set(bindings):
            attempt["backup_recovery_warning"] = "Some original reviewed files are missing from this backup. Keep the attempt blocked; restore the original files or a complete newer backup before recording."
            continue
        if any(digest(data) != bindings[raw][0] for raw, data in files.items()):
            raise IntakeError("Backup recovery files conflict with the selected local attempt.")
        capsule_id = digest(encoded_json(sorted((key, bindings[key]) for key in bindings)))[:24]
        mapping = {}
        for raw in files:
            name = PureWindowsPath(raw).name
            if not name or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.rstrip(". ") != name:
                raise IntakeError("Backup recovery artifact filename is invalid.")
            destination = (root / capsule_id / digest(raw.encode())[:24] / name).resolve()
            if not destination.is_relative_to(root):
                raise IntakeError("Backup recovery artifact destination escapes its app folder.")
            mapping[raw] = str(destination)
        hashes = {mapping[raw]: digest(data) for raw, data in files.items()}
        encoded = {}
        for role in ("attachment", "child_payload", "payload"):
            for raw, data in files.items():
                if bindings[raw][1] != role:
                    continue
                rebased = data if role == "attachment" else encoded_json(rebase_value(json.loads(data), mapping, hashes))
                encoded[mapping[raw]] = rebased
                hashes[mapping[raw]] = digest(rebased)
        for destination, data in encoded.items():
            path = Path(destination)
            if path.exists():
                if path.read_bytes() != data:
                    raise IntakeError("Restored recovery file conflicts with an existing local file. No history was replaced.")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                        temporary = Path(handle.name)
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, path)
                finally:
                    if temporary and temporary.exists():
                        temporary.unlink()
        original = copy.deepcopy(attempt)
        attempt.clear()
        attempt.update(rebase_value(original, mapping, hashes))
        attempt.pop("backup_capsule_pending", None)
        attempt["backup_original_target"] = original.get("backup_original_target", original["target"])
        attempt["backup_recovery_fingerprint"] = digest(encoded_json({key: attempt[key] for key in ("target", "requests", "gmail_create_draft_args")}))
        attempt["backup_recovery_warning"] = "Original reviewed files were restored for local recovery only. Prepare and review again before any new Gmail draft."
        all_mapping.update(mapping)
        all_hashes.update(hashes)
    return result, all_mapping, all_hashes
