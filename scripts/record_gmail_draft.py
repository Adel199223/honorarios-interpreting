from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.request_identity import normalize_case_number, normalize_period_label, request_identity_key
except ModuleNotFoundError:
    from request_identity import normalize_case_number, normalize_period_label, request_identity_key


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "data" / "gmail-draft-log.json"
DEFAULT_DUPLICATE_INDEX = ROOT / "data" / "duplicate-index.json"
STATUSES = {"active", "trashed", "superseded", "not_found", "sent"}


def load_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Draft log must be a list: {path}")
    return data


def write_log(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def duplicate_status_for_draft_status(status: str) -> str:
    return "drafted" if status == "active" else status


def duplicate_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return request_identity_key(record)


def load_duplicate_index(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Duplicate index must be a list: {path}")
    return data


def write_duplicate_index(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upsert_record(records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    draft_id = record["draft_id"]
    for existing in records:
        if existing.get("draft_id") == draft_id:
            for key, value in record.items():
                if value not in (None, "") or key in {"status", "updated_at", "notes"}:
                    existing[key] = value
            return
    records.append(record)


def upsert_duplicate_record(records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    draft_id = str(record.get("draft_id") or "").strip()
    record_key = duplicate_key(record)
    for existing in records:
        existing_draft_id = str(existing.get("draft_id") or "").strip()
        if draft_id and existing_draft_id == draft_id and duplicate_key(existing) == record_key:
            existing.update({key: value for key, value in record.items() if value not in (None, "")})
            return
    for existing in records:
        existing_draft_id = str(existing.get("draft_id") or "").strip()
        if not existing_draft_id and duplicate_key(existing) == record_key:
            existing.update({key: value for key, value in record.items() if value not in (None, "")})
            return
    records.append(record)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_payload(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Draft payload must be an object: {path}")
    return data


def first_attachment_path(payload: dict[str, Any]) -> str:
    attachments = payload.get("attachment_file_list") or payload.get("attachment_files") or []
    if isinstance(attachments, str):
        return attachments
    if isinstance(attachments, list) and attachments:
        return str(attachments[0])
    return ""


def required_value(value: str | None, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Missing required field: {field_name}")
    return text


def build_duplicate_record(record: dict[str, Any]) -> dict[str, Any]:
    duplicate = {
        "case_number": record["case_number"],
        "service_date": record["service_date"],
        "service_period_label": normalize_period_label(record.get("service_period_label", "")),
        "service_start_time": record.get("service_start_time", ""),
        "service_end_time": record.get("service_end_time", ""),
        "status": duplicate_status_for_draft_status(record["status"]),
        "draft_id": record["draft_id"],
        "message_id": record["message_id"],
        "thread_id": record.get("thread_id", ""),
        "draft_payload": record.get("draft_payload", ""),
        "pdf": record["pdf"],
        "pdf_sha256": record.get("pdf_sha256", ""),
        "recipient_email": record["recipient"],
        "source_filename": Path(record["pdf"]).name,
        "drafted_at": record["updated_at"],
        "updated_at": record["updated_at"],
        "notes": record.get("notes", ""),
    }
    if record.get("sent_date"):
        duplicate["sent_date"] = record["sent_date"]
    return duplicate


def duplicate_records_for_log_record(record: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    underlying = payload.get("underlying_requests") or []
    if not isinstance(underlying, list) or not underlying:
        return [build_duplicate_record(record)]

    records: list[dict[str, Any]] = []
    for item in underlying:
        if not isinstance(item, dict):
            continue
        child = dict(record)
        for key in ("case_number", "service_date", "service_period_label", "service_start_time", "service_end_time"):
            if item.get(key) not in (None, ""):
                child[key] = item[key]
        records.append(build_duplicate_record(child))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record or update a Gmail draft created for an honorários PDF.")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--duplicate-index", type=Path, default=DEFAULT_DUPLICATE_INDEX)
    parser.add_argument("--payload", type=Path, help="Draft payload JSON to derive case/date/recipient/PDF from.")
    parser.add_argument("--case-number")
    parser.add_argument("--service-date")
    parser.add_argument("--service-period-label")
    parser.add_argument("--service-start-time")
    parser.add_argument("--service-end-time")
    parser.add_argument("--recipient")
    parser.add_argument("--pdf")
    parser.add_argument("--draft-payload")
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--thread-id")
    parser.add_argument("--status", choices=sorted(STATUSES), default="active")
    parser.add_argument("--sent-date")
    parser.add_argument("--superseded-by")
    parser.add_argument("--supersedes", action="append", default=[])
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    try:
        records = load_log(args.log)
        payload_path = args.payload or (Path(args.draft_payload) if args.draft_payload else None)
        payload = load_payload(payload_path)
        pdf_value = args.pdf or first_attachment_path(payload)
        pdf_path = Path(required_value(pdf_value, "pdf")).resolve()
        service_period_label = args.service_period_label or str(payload.get("service_period_label") or "").strip()
        service_start_time = args.service_start_time or str(payload.get("service_start_time") or "").strip()
        service_end_time = args.service_end_time or str(payload.get("service_end_time") or "").strip()
        record = {
            "case_number": required_value(args.case_number or payload.get("case_number"), "case_number"),
            "service_date": required_value(args.service_date or payload.get("service_date"), "service_date"),
            "service_period_label": service_period_label,
            "service_start_time": service_start_time,
            "service_end_time": service_end_time,
            "recipient": required_value(args.recipient or payload.get("to"), "recipient"),
            "pdf": str(pdf_path),
            "pdf_sha256": file_sha256(pdf_path) if pdf_path.exists() else "",
            "draft_payload": str(payload_path.resolve()) if payload_path else "",
            "draft_id": args.draft_id,
            "message_id": args.message_id,
            "thread_id": args.thread_id or "",
            "status": args.status,
            "sent_date": args.sent_date or "",
            "superseded_by": args.superseded_by or "",
            "supersedes": args.supersedes,
            "notes": args.notes,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        upsert_record(records, record)
        write_log(args.log, records)
        duplicate_records = load_duplicate_index(args.duplicate_index)
        for duplicate_record in duplicate_records_for_log_record(record, payload):
            upsert_duplicate_record(duplicate_records, duplicate_record)
        write_duplicate_index(args.duplicate_index, duplicate_records)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Cannot record Gmail draft: {exc}", file=sys.stderr)
        return 2

    print(f"Recorded Gmail draft {args.draft_id} as {args.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
