"""Validate editable browser work for this runtime; never restore approvals."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from scripts.generate_pdf import IntakeError


def workspace_runtime_id(paths: Any) -> str:
    roots = [os.path.normcase(str(getattr(paths, name).resolve())) for name in
             ("personal_profiles", "duplicate_index", "draft_log", "source_upload_dir")]
    return hashlib.sha256(json.dumps(roots).encode("utf-8")).hexdigest()


def validate_workspace_resume(payload: dict[str, Any], paths: Any, profiles: dict[str, Any]) -> dict[str, Any]:
    if payload.get("workspace_id") != workspace_runtime_id(paths):
        raise IntakeError("This saved work belongs to a different app workspace. Open its original workspace to resume it.")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise IntakeError("The saved workspace format is invalid. Your current work was not changed.")
    if len(json.dumps(snapshot)) > 4_000_000:
        raise IntakeError("This saved workspace is too large to resume safely. Your current work was not changed.")
    cases, batch = snapshot.get("source_cases"), snapshot.get("batch_intakes")
    if not isinstance(cases, list) or not isinstance(batch, list) or max(len(cases), len(batch)) > 200:
        raise IntakeError("The saved case list is invalid. Your current work was not changed.")
    available = {str(profile["id"]) for profile in profiles.get("profiles", [])}
    replacement = str(payload.get("replacement_profile_id") or "")
    if replacement and replacement not in available:
        raise IntakeError("Choose an available personal profile before restoring these requests.")
    missing_profiles, missing_attachments, missing_sources = set(), set(), set()
    evidence = snapshot.get("current_evidence", {})
    choice = snapshot.get("travel_choice")
    if not isinstance(evidence, dict) or choice is not None and (
        not isinstance(choice, dict) or choice.get("mode") not in {"shared", "separate", "none"}
        or choice.get("ownerIndex") is not None and (not isinstance(choice.get("ownerIndex"), int)
                                                    or not 0 <= choice["ownerIndex"] < len(cases))
    ):
        raise IntakeError("The saved review inputs are invalid. Your current work was not changed.")
    forbidden = {"prepared_review", "preflight_review", "prepared_review_token", "review_fingerprint",
                 "gmail_handoff_reviewed", "draft_id", "message_id", "thread_id", "draft_payload",
                 "payload_paths", "manifest", "pdf", "pdf_sha256", "attachment_sha256", "png_preview_urls"}

    def editable(value: Any) -> Any:
        if isinstance(value, list):
            return [editable(item) for item in value]
        if isinstance(value, dict):
            return {key: editable(item) for key, item in value.items() if key not in forbidden and not key.endswith("_url")
                    and not any(word in key.lower() for word in ("token", "secret", "credential", "password", "authorization", "api_key", "raw_response", "provider_response"))}
        return value

    def retained_file(raw: Any, missing: set[str]) -> str:
        if not isinstance(raw, str) or not raw:
            return ""
        path = Path(raw).resolve()
        if not path.is_relative_to(paths.source_upload_dir.resolve()) or not path.is_file():
            missing.add(Path(raw).name)
            return ""
        return str(path)

    def intake(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise IntakeError("A saved request is invalid. Your current work was not changed.")
        row = editable(value)
        profile = str(row.get("personal_profile_id") or "")
        if profile not in available:
            if replacement:
                row["personal_profile_id"] = replacement
            else:
                missing_profiles.add(profile or "Unspecified profile")
        if row.get("source_file"):
            row["source_file"] = retained_file(row["source_file"], missing_sources)
        attachments = row.get("additional_attachment_files", [])
        if not isinstance(attachments, list):
            raise IntakeError("The saved attachment list is invalid. Your current work was not changed.")
        row["additional_attachment_files"] = [path for raw in attachments if (path := retained_file(raw, missing_attachments))]
        return row

    restored_cases = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("candidate_intake"), dict) or not isinstance(case.get("evidence", {}), dict):
            raise IntakeError("A saved source case is invalid. Your current work was not changed.")
        restored_cases.append({"candidate_intake": intake(case["candidate_intake"]), "evidence": editable(case.get("evidence", {})),
                               "answers": str(case.get("answers") or ""), "queued_key": str(case.get("queued_key") or "")})
    selected = snapshot.get("selected_case")
    selected = selected if isinstance(selected, int) and 0 <= selected < len(restored_cases) else (0 if len(restored_cases) > 1 else None)
    current = intake(snapshot.get("current_intake"))
    manual = intake(snapshot.get("manual_fields"))
    restored_batch = [intake(row) for row in batch]
    if any(row is None for row in restored_batch):
        raise IntakeError("A saved queued request is invalid. Your current work was not changed.")
    return {"status": "inputs_only", "workspace_id": workspace_runtime_id(paths), "send_allowed": False,
            "missing_attachments": sorted(missing_attachments), "missing_sources": sorted(missing_sources),
            "unavailable_profiles": sorted(missing_profiles), "snapshot": {
                "schema_version": 1, "current_intake": current, "current_evidence": editable(snapshot.get("current_evidence", {})),
                "source_cases": restored_cases, "selected_case": selected, "travel_choice": editable(snapshot.get("travel_choice")),
                "batch_intakes": restored_batch, "answers": str(snapshot.get("answers") or ""),
                "email_grouping": snapshot.get("email_grouping") if snapshot.get("email_grouping") in ("individual", "manual_visit") else "source",
                "packet_mode": snapshot.get("packet_mode") is True, "manual_fields": manual}}
