"""Conservative Gmail SENT reconciliation; provider access is GET-only.

The caller supplies the existing local status transition. It runs only after an
exact match and a fresh local snapshot check, under the shared history lock.
Uncertainty never retires a draft or removes duplicate protection.
"""
from __future__ import annotations

import base64
import binascii
from collections import Counter
import copy
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from scripts.request_identity import request_identity_key, validate_distinct_request_members
from scripts.build_email_draft import MANUAL_VISIT_FIELDS, SEPARATE_PDF_GROUP_MODES, manual_visit_group_metadata_errors, manual_visit_member_errors
from .backup import runtime_lock
from . import gmail_draft_api as gmail_api
from .runtime import SYNTHETIC_RUNTIME_ATTESTATION

AUTO_COOLDOWN_SECONDS = 60
MAX_SYNC_SECONDS = 45
MAX_HTTP_REQUESTS = 128
MAX_LIST_PAGES = 5
MAX_LIST_PAGE_SIZE = 50
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_MESSAGE_ATTACHMENT_BYTES = 100 * 1024 * 1024
MAX_WIRE_BYTES = 150 * 1024 * 1024
MAX_ATTACHMENTS = 64
MAX_MIME_PARTS = 256
MAX_LOCAL_RECORDS = 100
MAX_LOCAL_BYTES = 256 * 1024 * 1024
MAX_LOCAL_SECONDS = 15
FAKE_SENT_SYNC_ENV = "HONORARIOS_FAKE_GMAIL_SENT_SYNC_FOR_SMOKE"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
_ID = re.compile(r"[A-Za-z0-9_-]{1,512}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_sync_lock = threading.Lock()
_last_checks: dict[str, float] = {}
_next_record: dict[str, int] = {}
_last_results: dict[str, dict] = {}


class Unconfirmed(ValueError):
    """An incomplete or inconsistent check; its details never reach the UI."""


class LocalBudgetReached(Unconfirmed):
    pass


class LocalReadBudget:
    def __init__(self):
        self.remaining = MAX_LOCAL_BYTES
        self.deadline = time.monotonic() + MAX_LOCAL_SECONDS

    def spend(self, size: int):
        if size > self.remaining or time.monotonic() > self.deadline:
            raise LocalBudgetReached("Local evidence budget reached")
        self.remaining -= size


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_hash(value: Any) -> str:
    return _digest(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise Unconfirmed("Invalid provider identifier")
    return value


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise Unconfirmed("Missing creation time")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise Unconfirmed("Unknown creation time") from exc


def _addresses(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip() or len(value) > 8192 or "\x00" in value:
        raise Unconfirmed("Unknown recipient")
    addresses = getaddresses([value])
    result = []
    for _label, address in addresses:
        if not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", address):
            raise Unconfirmed("Unknown recipient")
        result.append(address.casefold())
    if not result or len(set(result)) != len(result):
        raise Unconfirmed("Unknown recipient")
    return tuple(sorted(result))


def _subject(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise Unconfirmed("Unknown subject")
    try:
        return str(make_header(decode_header(re.sub(r"\r?\n[ \t]+", " ", value)))).strip()
    except (ValueError, LookupError) as exc:
        raise Unconfirmed("Unknown subject") from exc


def _local_bytes(raw: Any, roots: list[Path], limit: int, budget: LocalReadBudget | None = None) -> tuple[Path, bytes]:
    if not isinstance(raw, (str, Path)) or not str(raw):
        raise Unconfirmed("Missing local artifact")
    path = Path(raw)
    if not path.is_absolute() or path.is_symlink():
        raise Unconfirmed("Invalid local artifact")
    resolved = path.resolve(strict=True)
    if not any(resolved.is_relative_to(root.resolve()) for root in roots):
        raise Unconfirmed("Artifact outside managed output")
    with resolved.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise Unconfirmed("Invalid artifact size")
        if budget is not None:
            budget.spend(before.st_size)
        content = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    current = resolved.stat()
    fields = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    if (len(content) != before.st_size or len(content) > limit or fields(before) != fields(after)
            or fields(after) != fields(current) or path.resolve(strict=True) != resolved):
        raise Unconfirmed("Local artifact changed")
    return resolved, content


def _read_json(path: Path, limit: int = MAX_JSON_BYTES, budget: LocalReadBudget | None = None) -> Any:
    with path.open("rb") as handle:
        if budget is not None:
            budget.spend(os.fstat(handle.fileno()).st_size)
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise Unconfirmed("Local JSON too large")
    return json.loads(content)


def _history(paths: Any) -> tuple[list[dict], list[dict]]:
    records, index = _read_json(paths.draft_log), _read_json(paths.duplicate_index)
    if not isinstance(records, list) or not isinstance(index, list) or any(not isinstance(row, dict) for row in [*records, *index]):
        raise Unconfirmed("Invalid local history")
    return records, index


def _creation_attempts(paths: Any, budget: LocalReadBudget | None = None) -> list[dict]:
    journal = paths.draft_log.with_name("gmail-create-attempts.local.json")
    if not journal.exists():
        return []
    value = _read_json(journal, 8 * MAX_JSON_BYTES, budget)
    if not isinstance(value, dict) or not isinstance(value.get("attempts"), list):
        raise Unconfirmed("Invalid creation journal")
    return value["attempts"]


def _review_anchor(record: dict, paths: Any, artifacts: dict[str, str], hashes: dict[str, str], attempts: list[dict]) -> tuple[datetime, str]:
    attempts = [row for row in attempts if isinstance(row, dict) and isinstance(row.get("gmail_result"), dict)
                and row["gmail_result"].get("draft_id") == record["draft_id"]]
    if attempts:
        if len(attempts) != 1:
            raise Unconfirmed("Ambiguous creation evidence")
        attempt = attempts[0]
        target = attempt.get("target")
        if not isinstance(target, dict) or attempt.get("gmail_result", {}).get("message_id") != record.get("message_id"):
            raise Unconfirmed("Creation binding changed")
        raw_payload = str(Path(record["draft_payload"]).resolve())
        if (target.get("draft_payload") != raw_payload or target.get("draft_payload_sha256") != artifacts.get(raw_payload)
                or target.get("attachment_sha256") != hashes):
            raise Unconfirmed("Reviewed payload changed")
        child_hashes = target.get("child_payload_sha256") or {}
        expected_children = {path: digest for path, digest in artifacts.items() if path not in hashes and path != raw_payload}
        if child_hashes != expected_children:
            raise Unconfirmed("Reviewed child payload changed")
        return _instant(attempt.get("created_at")), _json_hash(attempt)
    payload_hash = artifacts.get(str(Path(record["draft_payload"]).resolve()))
    if record.get("draft_payload_sha256") != payload_hash:
        raise Unconfirmed("Legacy request has no immutable reviewed payload binding")
    return _instant(record.get("created_at")), _json_hash([record["draft_payload_sha256"], record["created_at"]])


def _snapshot(record: dict, index: list[dict], paths: Any, *, budget: LocalReadBudget | None = None, attempts: list[dict] | None = None) -> dict:
    draft_id = _identifier(record.get("draft_id"))
    if record.get("status") != "active":
        raise Unconfirmed("Record no longer active")
    _identifier(record.get("message_id"))
    payload_path, payload_bytes = _local_bytes(record.get("draft_payload"), [paths.draft_output_dir], MAX_JSON_BYTES, budget)
    payload = json.loads(payload_bytes)
    if not isinstance(payload, dict) or payload.get("send_allowed") is not False or payload.get("draft_only") is not True:
        raise Unconfirmed("Unreviewed payload")
    args = payload.get("gmail_create_draft_args")
    if not isinstance(args, dict) or payload.get("gmail_create_draft_ready") is not True:
        raise Unconfirmed("Unreviewed payload")
    recipient = _addresses(args.get("to"))
    subject = _subject(args.get("subject"))
    if recipient != _addresses(record.get("recipient")) or recipient != _addresses(payload.get("to")) or subject != _subject(payload.get("subject")):
        raise Unconfirmed("Payload binding changed")
    if args.get("cc") or args.get("bcc"):
        raise Unconfirmed("Unsupported recipient set")
    attachments = payload.get("attachment_files")
    hashes = payload.get("attachment_sha256")
    if (not isinstance(attachments, list) or not 1 <= len(attachments) <= MAX_ATTACHMENTS
            or args.get("attachment_files") != attachments or not isinstance(hashes, dict)
            or any(not isinstance(raw, str) for raw in attachments)
            or len(set(attachments)) != len(attachments) or set(hashes) != set(attachments)):
        raise Unconfirmed("Unknown attachment set")
    artifacts = {str(payload_path): _digest(payload_bytes)}
    total = 0
    attachment_roots = [paths.output_dir, paths.packet_output_dir, paths.source_upload_dir]
    for raw in attachments:
        expected = hashes.get(raw)
        if not isinstance(expected, str) or not _HASH.fullmatch(expected):
            raise Unconfirmed("Unknown attachment hash")
        path, content = _local_bytes(raw, attachment_roots, MAX_ATTACHMENT_BYTES, budget)
        total += len(content)
        if total > MAX_MESSAGE_ATTACHMENT_BYTES or _digest(content) != expected:
            raise Unconfirmed("Attachment changed")
        artifacts[str(path)] = expected
    requests = payload.get("underlying_requests") or [payload]
    if not isinstance(requests, list):
        raise Unconfirmed("Unknown group membership")
    validate_distinct_request_members(requests)
    keys = {request_identity_key(row) for row in requests}
    recorded_requests = record.get("underlying_requests") or [record]
    if not isinstance(recorded_requests, list) or any(not isinstance(row, dict) for row in recorded_requests) or {request_identity_key(row) for row in recorded_requests} != keys:
        raise Unconfirmed("Group membership changed")
    matched_index = [row for row in index if row.get("draft_id") == draft_id]
    if (len(matched_index) != len(keys) or {request_identity_key(row) for row in matched_index} != keys
            or any(row.get("status") not in {"drafted", "sent"} for row in matched_index)):
        raise Unconfirmed("Duplicate protection has different membership")
    if payload.get("email_grouping") in SEPARATE_PDF_GROUP_MODES:
        manual_visit = payload.get('email_grouping') == 'manual_visit'
        if (record.get("underlying_requests") != requests or record.get('email_grouping') != payload.get('email_grouping')
                or record.get('email_group_id') != payload.get('email_group_id')):
            raise Unconfirmed("Group metadata changed")
        if manual_visit and (record.get('manual_visit_id') != payload.get('manual_visit_id')
                             or manual_visit_group_metadata_errors(payload, requests)):
            raise Unconfirmed('Manual visit metadata changed')
        for child in requests:
            if child.get("pdf") not in attachments or hashes.get(child.get("pdf")) != child.get("pdf_sha256"):
                raise Unconfirmed("Missing child PDF")
            child_path, child_bytes = _local_bytes(child.get("draft_payload"), [paths.draft_output_dir], MAX_JSON_BYTES, budget)
            if _digest(child_bytes) != child.get("draft_payload_sha256"):
                raise Unconfirmed("Child payload changed")
            child_payload = json.loads(child_bytes)
            if not isinstance(child_payload, dict) or request_identity_key(child_payload) != request_identity_key(child):
                raise Unconfirmed("Child identity changed")
            if manual_visit and (manual_visit_member_errors(payload, child_payload)
                                 or any(child.get(key) != child_payload.get(key) for key in MANUAL_VISIT_FIELDS)
                                 or any(child.get(key) != child_payload.get(key) for key in ('claim_interpreting', 'claim_transport', 'travel_group_id', 'travel_group_binding'))):
                raise Unconfirmed('Manual visit child payload changed')
            artifacts[str(child_path)] = _digest(child_bytes)
        if manual_visit:
            by_key = {request_identity_key(child): child for child in requests}
            for row in matched_index:
                child = by_key[request_identity_key(row)]
                if any(row.get(key) != child.get(key) for key in MANUAL_VISIT_FIELDS):
                    raise Unconfirmed('Protected manual visit metadata changed')
    if record.get("pdf") not in attachments or hashes.get(record.get("pdf")) != record.get("pdf_sha256"):
        raise Unconfirmed("Recorded PDF changed")
    for child in matched_index:
        if child.get("pdf") not in attachments or hashes.get(child.get("pdf")) != child.get("pdf_sha256"):
            raise Unconfirmed("Protected child PDF changed")
    anchored_at, anchor_hash = _review_anchor(record, paths, artifacts, hashes, attempts if attempts is not None else _creation_attempts(paths, budget))
    created = max(_instant(record["created_at"]), anchored_at) if record.get("created_at") else anchored_at
    return {"record": copy.deepcopy(record), "payload": payload, "created_at": created,
            "recipient": recipient, "subject": subject, "hashes": sorted(hashes.values()),
            "artifacts": artifacts, "binding": _json_hash([record, matched_index, artifacts, anchor_hash])}


def _synthetic_mode(paths: Any) -> bool:
    marker = paths.synthetic_runtime_marker
    if not marker.exists():
        return False
    value = _read_json(marker, 64 * 1024)
    if not isinstance(value, dict) or value.get("attestation") != SYNTHETIC_RUNTIME_ATTESTATION or value.get("isolated_runtime") is not True or value.get("synthetic_runtime") is not True:
        raise Unconfirmed("Invalid synthetic marker")
    return True


def fake_gmail_sent_sync_enabled(paths: Any) -> bool:
    """Secret-free status helper; fake readiness requires an isolated fixture root."""
    try:
        return (str(os.environ.get(FAKE_SENT_SYNC_ENV) or "").lower() in {"1", "true", "yes", "on"}
                and _synthetic_mode(paths))
    except (OSError, ValueError, TypeError):
        return False


def _verified_draft_present(value: dict | None, draft_id: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, dict) or value.get("id") != draft_id or not isinstance(value.get("message"), dict):
        raise Unconfirmed("Unknown draft response")
    message = value["message"]
    _identifier(message.get("id"))
    labels = message.get("labelIds")
    # Gmail can still resolve an old draft ID to its now-SENT message. Resource
    # existence alone does not establish that a draft remains.
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels) or "DRAFT" not in labels or "SENT" in labels:
        raise Unconfirmed("Draft state is not confirmed")
    return True


class GmailSentReader:
    """Bounded read-only transport; no arbitrary URLs or write methods."""
    def __init__(self, access_token: str):
        self.client = httpx.Client(timeout=15, follow_redirects=False)
        self.headers = {"Authorization": f"Bearer {access_token}"}
        self.deadline = time.monotonic() + MAX_SYNC_SECONDS
        self.requests = 0
        self.wire_bytes = 0

    def close(self):
        self.client.close()

    def _get(self, url: str, *, params: dict | None = None, attachment: bool = False, allow_missing: bool = False) -> dict | None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or self.requests >= MAX_HTTP_REQUESTS:
            raise Unconfirmed("Sync read budget reached")
        self.requests += 1
        limit = (MAX_ATTACHMENT_BYTES * 4 // 3 + 4096) if attachment else (MAX_MESSAGE_ATTACHMENT_BYTES * 4 // 3 + MAX_JSON_BYTES)
        with self.client.stream("GET", url, headers=self.headers, params=params, timeout=min(15, remaining)) as response:
            if allow_missing and response.status_code == 404:
                return None
            if response.status_code != 200:
                raise Unconfirmed("Gmail read unavailable")
            raw = bytearray()
            for chunk in response.iter_bytes():
                self.wire_bytes += len(chunk)
                if self.wire_bytes > MAX_WIRE_BYTES or len(raw) + len(chunk) > limit or time.monotonic() > self.deadline:
                    raise Unconfirmed("Sync read budget reached")
                raw.extend(chunk)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise Unconfirmed("Invalid Gmail response")
        return value

    def get(self, suffix: str = "", *, params: dict | None = None, attachment: bool = False) -> dict:
        return self._get(GMAIL_MESSAGES_URL + suffix, params=params, attachment=attachment)

    def draft_exists(self, draft_id: str) -> bool:
        value = self._get(GMAIL_DRAFTS_URL + "/" + quote(_identifier(draft_id), safe=""), params={"format": "minimal"}, allow_missing=True)
        return _verified_draft_present(value, draft_id)


class FixtureSentReader:
    """Same matching path with explicitly seeded offline Gmail-shaped fixtures."""
    def __init__(self, paths: Any):
        fixture = _read_json(paths.gmail_config.with_name("gmail-sent-sync-fixture.local.json"), 5 * 1024 * 1024)
        if not isinstance(fixture, dict) or not isinstance(fixture.get("messages"), list):
            raise Unconfirmed("Missing synthetic fixture")
        self.messages = fixture["messages"]
        self.attachments = fixture.get("attachments", {})
        self.drafts = fixture.get("drafts", {})

    def close(self):
        pass

    def draft_exists(self, draft_id: str) -> bool:
        if not isinstance(self.drafts, dict) or draft_id not in self.drafts:
            raise Unconfirmed("Missing synthetic draft status")
        return _verified_draft_present(self.drafts[draft_id], draft_id)

    def get(self, suffix: str = "", *, params: dict | None = None, attachment: bool = False) -> dict:
        if not suffix:
            offset = int((params or {}).get("pageToken") or 0)
            rows = self.messages[offset:offset + MAX_LIST_PAGE_SIZE]
            result = {"messages": [{"id": row["id"]} for row in rows]}
            if offset + len(rows) < len(self.messages):
                result["nextPageToken"] = str(offset + len(rows))
            return result
        parts = suffix.strip("/").split("/")
        if len(parts) == 3 and parts[1] == "attachments":
            result = self.attachments.get(parts[0] + "/" + parts[2])
        else:
            result = next((row for row in self.messages if row.get("id") == parts[0]), None)
        if not isinstance(result, dict):
            raise Unconfirmed("Missing synthetic message")
        return copy.deepcopy(result)


def _headers(payload: dict) -> dict[str, str]:
    rows = payload.get("headers")
    if not isinstance(rows, list) or len(rows) > 200:
        raise Unconfirmed("Unknown message headers")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not isinstance(row.get("value"), str):
            raise Unconfirmed("Invalid message header")
        name = row["name"].casefold()
        if name in {"to", "subject", "cc", "bcc"}:
            if name in result:
                raise Unconfirmed("Repeated recipient or subject header")
            result[name] = row["value"]
    return result


def _attachment_parts(payload: dict) -> list[dict]:
    result, stack, visited = [], [(payload, 0)], 0
    while stack:
        part, depth = stack.pop()
        visited += 1
        if not isinstance(part, dict) or visited > MAX_MIME_PARTS or depth > 16:
            raise Unconfirmed("Unknown MIME structure")
        children = part.get("parts") or []
        if not isinstance(children, list):
            raise Unconfirmed("Unknown MIME structure")
        filename = part.get("filename")
        headers = part.get("headers") or []
        if not isinstance(headers, list):
            raise Unconfirmed("Unknown MIME headers")
        disposition = next((str(row.get("value") or "") for row in headers if isinstance(row, dict) and str(row.get("name") or "").casefold() == "content-disposition"), "")
        is_attachment = bool(filename) or disposition.casefold().startswith("attachment")
        if is_attachment:
            if children or not isinstance(part.get("body"), dict):
                raise Unconfirmed("Unknown attachment structure")
            result.append(part["body"])
        elif children:
            stack.extend((child, depth + 1) for child in children)
        elif str(part.get("mimeType") or "").casefold() not in {"text/plain", "text/html"}:
            raise Unconfirmed("Unknown unnamed message part")
    if not 1 <= len(result) <= MAX_ATTACHMENTS:
        raise Unconfirmed("Unknown attachment set")
    return result


def _decode_attachment(body: dict) -> bytes:
    size, data = body.get("size"), body.get("data")
    if type(size) is not int or not 0 < size <= MAX_ATTACHMENT_BYTES or not isinstance(data, str) or len(data) > MAX_ATTACHMENT_BYTES * 4 // 3 + 4:
        raise Unconfirmed("Unknown attachment bytes")
    try:
        content = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise Unconfirmed("Invalid attachment encoding") from exc
    if len(content) != size:
        raise Unconfirmed("Incomplete attachment")
    return content


def _match_message(message: dict, snapshot: dict, reader: Any, upper_time: datetime) -> dict | None:
    labels = message.get("labelIds")
    if not isinstance(labels, list) or "SENT" not in labels or "DRAFT" in labels:
        return None
    message_id = _identifier(message.get("id"))
    thread_id = _identifier(message.get("threadId"))
    timestamp = message.get("internalDate")
    if not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{1,16}", timestamp):
        raise Unconfirmed("Missing sent timestamp")
    try:
        sent_at = datetime.fromtimestamp(int(timestamp) / 1000, timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise Unconfirmed("Invalid sent timestamp") from exc
    if sent_at < snapshot["created_at"] or sent_at > upper_time:
        return None
    payload = message.get("payload")
    if not isinstance(payload, dict):
        raise Unconfirmed("Unknown message content")
    headers = _headers(payload)
    if (_addresses(headers.get("to")) != snapshot["recipient"] or _subject(headers.get("subject")) != snapshot["subject"]
            or headers.get("cc", "").strip() or headers.get("bcc", "").strip()):
        return None
    parts = _attachment_parts(payload)
    if len(parts) != len(snapshot["hashes"]):
        return None
    hashes, total = [], 0
    for part in parts:
        size = part.get("size")
        if type(size) is not int or not 0 < size <= MAX_ATTACHMENT_BYTES:
            raise Unconfirmed("Unknown attachment size")
        total += size
        if total > MAX_MESSAGE_ATTACHMENT_BYTES:
            raise Unconfirmed("Attachments exceed read budget")
        if part.get("attachmentId"):
            attachment_id = _identifier(part["attachmentId"])
            body = reader.get("/" + quote(message_id, safe="") + "/attachments/" + quote(attachment_id, safe=""), attachment=True)
            if body.get("size") != size:
                raise Unconfirmed("Attachment size changed")
        else:
            body = part
        hashes.append(_digest(_decode_attachment(body)))
    if Counter(hashes) != Counter(snapshot["hashes"]):
        return None
    return {"sent_message_id": message_id, "sent_thread_id": thread_id,
            "sent_at": sent_at.isoformat(), "sent_date": sent_at.astimezone(ZoneInfo("Europe/Lisbon")).date().isoformat(),
            "sent_verified_at": datetime.now(timezone.utc).isoformat(),
            "verification_method": "gmail_sent_exact_attachments", "attachment_sha256": sorted(hashes)}


def _find_match(snapshot: dict, reader: Any, upper_time: datetime) -> dict | None:
    # No rolling recent-date cutoff: even old active drafts retain their window.
    after = int(snapshot["created_at"].timestamp()) - 1
    before = int(upper_time.timestamp()) + 1
    subject = snapshot["subject"].replace("\\", "\\\\").replace('"', '\\"')
    query = f'after:{after} before:{before} subject:"{subject}" ' + " ".join(f"to:{address}" for address in snapshot["recipient"])
    token, seen_tokens, seen_ids, matches = "", set(), set(), []
    for _page in range(MAX_LIST_PAGES):
        params = {"labelIds": "SENT", "q": query, "includeSpamTrash": "true", "maxResults": MAX_LIST_PAGE_SIZE}
        if token:
            params["pageToken"] = token
        page = reader.get(params=params)
        rows = page.get("messages", [])
        if not isinstance(rows, list) or len(rows) > MAX_LIST_PAGE_SIZE:
            raise Unconfirmed("Incomplete message listing")
        for row in rows:
            if not isinstance(row, dict):
                raise Unconfirmed("Invalid message listing")
            message_id = _identifier(row.get("id"))
            if message_id in seen_ids:
                continue
            seen_ids.add(message_id)
            message = reader.get("/" + quote(message_id, safe=""), params={"format": "full"})
            if message.get("id") != message_id:
                raise Unconfirmed("Message identity mismatch")
            matched = _match_message(message, snapshot, reader, upper_time)
            if matched:
                matches.append(matched)
                if len(matches) > 1:
                    raise Unconfirmed("Multiple exact sent matches")
        token = page.get("nextPageToken") or ""
        if not token:
            return matches[0] if matches else None
        if not isinstance(token, str) or len(token) > 2048 or token in seen_tokens:
            raise Unconfirmed("Incomplete pagination")
        seen_tokens.add(token)
    raise Unconfirmed("Search window exceeded bounded pagination")


def _result(status: str, **values: Any) -> dict:
    return {"status": status, "checked_count": 0, "sent_count": 0, "unchanged_count": 0,
            "still_drafted_count": 0, "needs_review_count": 0, "error_count": 0,
            "warnings": [],
            "cooldown_seconds": AUTO_COOLDOWN_SECONDS, "gmail_write_allowed": False,
            "send_allowed": False, "managed_data_changed": False, **values}


def sent_sync_last_result(paths: Any) -> dict | None:
    """Return only the previous completed check, never a fresh fabricated time."""
    return copy.deepcopy(_last_results.get(str(paths.draft_log.resolve())))


def _finished(key: str, result: dict) -> dict:
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    _last_results[key] = copy.deepcopy(result)
    return result


def _idle_result(key: str, status: str, **values: Any) -> dict:
    previous = _last_results.get(key)
    base = copy.deepcopy(previous) if previous is not None else {
        "gmail_write_allowed": False, "send_allowed": False, "managed_data_changed": False,
        "warnings": [], "cooldown_seconds": AUTO_COOLDOWN_SECONDS}
    return {**base, "status": status, "managed_data_changed": False, **values}


def sync_gmail_sent_status(paths: Any, *, force: bool = False, apply_confirmed: Callable[[dict, dict], Any]) -> dict:
    """Check active drafts, then call the local transition with the history lock held.

    The callback must not reacquire runtime/history locks. Its domain update must
    preserve all old metadata and IDs while marking every protected child sent.
    """
    key = str(paths.draft_log.resolve())
    if not _sync_lock.acquire(blocking=False):
        return _idle_result(key, "busy", warnings=["A sent-status check is already running."])
    reader = None
    try:
        now = time.monotonic()
        if not force and now - _last_checks.get(key, float("-inf")) < AUTO_COOLDOWN_SECONDS:
            return _idle_result(key, "cooldown", cooldown_seconds=max(1, int(AUTO_COOLDOWN_SECONDS - (now - _last_checks[key]))))
        fake = str(os.environ.get(FAKE_SENT_SYNC_ENV) or "").lower() in {"1", "true", "yes", "on"}
        synthetic = _synthetic_mode(paths)
        if fake != synthetic:
            return _idle_result(key, "error", warnings=["Sent-status checking is unavailable in this runtime."])
        if not fake and not gmail_api.gmail_sent_read_ready(paths.gmail_config):
            return _idle_result(key, "authorization_required", warnings=["Connect Gmail sent-status access to check sent messages."])
        _last_checks[key] = now
        with runtime_lock(paths.draft_log):
            records, index = _history(paths)
            active = [row for row in records if row.get("status") == "active"]
            if len({row.get("draft_id") for row in active}) != len(active):
                raise Unconfirmed("Repeated local draft IDs")
            start = _next_record.get(key, 0) % len(active) if active else 0
            ordered_active = active[start:] + active[:start]
            snapshots, unavailable, scanned = [], 0, 0
            local_budget = LocalReadBudget()
            attempts = _creation_attempts(paths, local_budget)
            for position, record in enumerate(ordered_active):
                if position >= MAX_LOCAL_RECORDS:
                    break
                try:
                    snapshot = _snapshot(record, index, paths, budget=local_budget, attempts=attempts)
                    snapshot["rotation_position"] = (start + position) % len(active)
                    snapshots.append(snapshot)
                except LocalBudgetReached:
                    break
                except (Unconfirmed, OSError, ValueError, TypeError):
                    unavailable += 1
                scanned += 1
            unavailable += len(active) - scanned
            _next_record[key] = (start + max(scanned, 1)) % len(active) if active else 0
        if not active:
            return _finished(key, _result("complete"))
        if not snapshots:
            return _finished(key, _result("partial", unchanged_count=len(active), needs_review_count=len(active), warnings=["Some saved requests lack unchanged evidence; their status and duplicate protection were kept."]))
        if fake:
            reader = FixtureSentReader(paths)
        else:
            access_token, _ = gmail_api.gmail_access_token(paths.gmail_config)
            if not gmail_api.gmail_sent_read_ready(paths.gmail_config):
                raise Unconfirmed("Sent read authorization changed")
            reader = GmailSentReader(access_token)
        upper_time = datetime.now(timezone.utc)
        confirmed, checked, uncertain, still_drafted, errors = [], 0, unavailable, 0, 0
        for snapshot in snapshots:
            if isinstance(reader, GmailSentReader) and (reader.requests >= MAX_HTTP_REQUESTS or time.monotonic() >= reader.deadline):
                _next_record[key] = snapshot["rotation_position"]
                break
            checked += 1
            try:
                # Exact SENT evidence is authoritative even if the old draft ID
                # still resolves, a draft copy survives, or draft lookup fails.
                evidence = _find_match(snapshot, reader, upper_time)
                if evidence:
                    confirmed.append((snapshot, evidence))
                elif reader.draft_exists(snapshot["record"]["draft_id"]):
                    still_drafted += 1
            except (Unconfirmed, OSError, ValueError, TypeError, httpx.HTTPError):
                uncertain += 1
                errors += 1
        # One remote message cannot establish two separately recorded emails.
        counts = Counter(evidence["sent_message_id"] for _, evidence in confirmed)
        sent, managed_changed = 0, False
        commit_budget = LocalReadBudget()
        for snapshot, evidence in confirmed:
            if counts[evidence["sent_message_id"]] != 1:
                uncertain += 1
                continue
            try:
                with runtime_lock(paths.draft_log):
                    current_records, current_index = _history(paths)
                    candidates = [row for row in current_records if row.get("draft_id") == snapshot["record"]["draft_id"]]
                    if len(candidates) != 1 or _snapshot(candidates[0], current_index, paths, budget=commit_budget)["binding"] != snapshot["binding"]:
                        raise Unconfirmed("History or artifacts changed during Gmail read")
                    if any((row.get("status") or "sent") == "sent" and row.get("draft_id") != candidates[0]["draft_id"]
                           and (row.get("sent_message_id") or row.get("message_id")) == evidence["sent_message_id"]
                           for row in [*current_records, *current_index]):
                        raise Unconfirmed("Sent message already belongs to another recorded request")
                    before_commit = _json_hash([current_records, current_index])
                    try:
                        apply_confirmed(copy.deepcopy(candidates[0]), copy.deepcopy(evidence))
                    except (OSError, ValueError, TypeError):
                        # A safe index-first domain write can need forward repair
                        # after its second write fails. Report that local change.
                        managed_changed = managed_changed or _json_hash(_history(paths)) != before_commit
                        raise
                    managed_changed = True
                sent += 1
            except (Unconfirmed, OSError, ValueError, TypeError):
                uncertain += 1
        needs_review = len(active) - sent - still_drafted
        warnings = ["Some checks could not confirm an exact sent email; those requests keep their duplicate protection and need review."] if needs_review else []
        return _finished(key, _result("partial" if needs_review else "complete", checked_count=checked, sent_count=sent, unchanged_count=len(active) - sent,
                       still_drafted_count=still_drafted, needs_review_count=len(active) - sent - still_drafted, error_count=errors,
                       warnings=warnings, managed_data_changed=managed_changed))
    except (Unconfirmed, OSError, ValueError, TypeError, httpx.HTTPError):
        return _idle_result(key, "error", warnings=["Sent-status checking could not finish. Existing duplicate protection was kept."])
    finally:
        try:
            if reader is not None:
                try:
                    reader.close()
                except (OSError, RuntimeError, httpx.HTTPError):
                    pass
        finally:
            _sync_lock.release()
