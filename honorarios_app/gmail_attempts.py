"""Durable, local draft-create attempts; no Gmail or other network calls."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
from typing import Any

from scripts.generate_pdf import IntakeError
from scripts.request_identity import request_identity_key
from scripts.state_store import atomic_write_json, state_file_lock


def attempt_paths(draft_log: Path) -> tuple[Path, Path]:
    return (draft_log.with_name("gmail-create-attempts.local.json"),
            draft_log.with_name(".gmail-create-attempts.lock"))


def attempt_lock(draft_log: Path):
    return state_file_lock(attempt_paths(draft_log)[1])


def load_attempts(draft_log: Path) -> list[dict[str, Any]]:
    path = attempt_paths(draft_log)[0]
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IntakeError("The Gmail attempt journal cannot be read. Restore or inspect it before creating another draft.") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("attempts"), list):
        raise IntakeError("The Gmail attempt journal is invalid. Inspect it before creating another draft.")
    attempts = value["attempts"]
    if any(not isinstance(row, dict) or not row.get("attempt_id") or not isinstance(row.get("requests"), list) or not row["requests"] for row in attempts):
        raise IntakeError("The Gmail attempt journal contains an invalid entry. Inspect it before creating another draft.")
    return attempts


def save_attempts(draft_log: Path, attempts: list[dict[str, Any]]) -> None:
    atomic_write_json(attempt_paths(draft_log)[0], {"schema_version": 1, "attempts": attempts})


def update_attempt(attempt: dict[str, Any], **fields: Any) -> None:
    attempt.update(fields, updated_at=datetime.now(timezone.utc).isoformat())


def new_attempt(requests: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    result = {"attempt_id": secrets.token_hex(16), "requests": requests,
              "created_at": datetime.now(timezone.utc).isoformat()}
    update_attempt(result, state="started", **fields)
    return result


def pending_attempt(attempts: list[dict[str, Any]], requests: list[dict[str, Any]]) -> dict[str, Any] | None:
    keys = [request_identity_key(row) for row in requests]
    for attempt in attempts:
        if attempt.get("state") in {"recorded", "not_created", "confirmed_not_created"}:
            continue
        previous = [request_identity_key(row) for row in attempt["requests"]]
        if any(old[:2] == new[:2] and (not old[2] or not new[2] or old[2] == new[2]) for old in previous for new in keys):
            return attempt
    return None
