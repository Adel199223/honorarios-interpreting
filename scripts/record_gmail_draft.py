from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.request_identity import normalize_case_number, normalize_period_label, request_identity_key, request_identity_keys_overlap, validate_distinct_request_members
    from scripts.claim_options import recorded_travel_requests, validate_travel_payload_groups
    from scripts.build_email_draft import MANUAL_VISIT_FIELDS, SEPARATE_PDF_GROUP_MODES, source_email_group_errors, validate_draft_payload
    from scripts.state_store import atomic_write_json, state_file_lock
except ModuleNotFoundError:
    from request_identity import normalize_case_number, normalize_period_label, request_identity_key, request_identity_keys_overlap, validate_distinct_request_members
    from claim_options import recorded_travel_requests, validate_travel_payload_groups
    from build_email_draft import MANUAL_VISIT_FIELDS, SEPARATE_PDF_GROUP_MODES, source_email_group_errors, validate_draft_payload
    from state_store import atomic_write_json, state_file_lock


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "data" / "gmail-draft-log.json"
DEFAULT_DUPLICATE_INDEX = ROOT / "data" / "duplicate-index.json"
STATUSES = {"active", "trashed", "superseded", "not_found", "sent"}
CLAIM_FIELDS = ('claim_interpreting', 'claim_transport', 'travel_group_id', 'travel_group_binding')
EMAIL_GROUP_FIELDS = ('email_grouping', 'email_group_id', 'source_sha256', 'personal_profile_id', *MANUAL_VISIT_FIELDS)


def load_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Draft log must be a list: {path}")
    return data


def write_log(path: Path, records: list[dict[str, Any]]) -> None:
    atomic_write_json(path, records)


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
    atomic_write_json(path, records)


def apply_verified_sent_unlocked(log_path: Path, index_path: Path, snapshot: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Commit verified Gmail evidence under the caller's shared runtime/history lock.

    Index first keeps every identity blocking if the second atomic replace fails.
    A subsequent sync can repair an active log with the same already-sent children.
    Original IDs, payloads, timestamps, claims and unknown historical fields survive.
    """
    records = load_log(log_path)
    index = load_duplicate_index(index_path)
    draft_id = str(snapshot.get('draft_id') or '')
    matching = [row for row in records if row.get('draft_id') == draft_id]
    if not draft_id or len(matching) != 1 or matching[0] != snapshot or snapshot.get('status') != 'active':
        raise ValueError('Draft history changed while checking Gmail. Check again.')
    children = snapshot.get('underlying_requests') or [snapshot]
    if not isinstance(children, list) or not children or any(not isinstance(row, dict) for row in children):
        raise ValueError('Draft request membership needs review.')
    keys = [request_identity_key(row) for row in children]
    if len(set(keys)) != len(keys) or any(not all(key[:2]) for key in keys):
        raise ValueError('Draft request identities need review.')
    linked = [row for row in index if row.get('draft_id') == draft_id]
    if len(linked) != len(keys) or {request_identity_key(row) for row in linked} != set(keys):
        raise ValueError('Draft history and duplicate protection do not cover the same requests.')
    fields = ('sent_message_id', 'sent_thread_id', 'sent_at', 'sent_date', 'sent_verified_at', 'verification_method', 'attachment_sha256')
    if any(not evidence.get(key) for key in fields) or evidence.get('verification_method') != 'gmail_sent_exact_attachments':
        raise ValueError('Verified sent evidence is incomplete.')
    if any(row.get('status') not in {'drafted', 'sent'} for row in linked):
        raise ValueError('A draft request has been retired or changed. Review its history.')
    for row in linked:
        if row.get('status') == 'sent' and (row.get('sent_message_id') != evidence['sent_message_id']
                or row.get('sent_at') != evidence['sent_at']):
            raise ValueError('Existing sent evidence differs. Review its history.')
    proof = {key: copy.deepcopy(evidence[key]) for key in fields}
    proof['sent_attachment_sha256'] = proof.pop('attachment_sha256')
    for row in linked:
        row.update(proof)
        row.update(status='sent', updated_at=evidence['sent_verified_at'])
    matching[0].update(proof)
    matching[0].update(status='sent', updated_at=evidence['sent_verified_at'])
    write_duplicate_index(index_path, index)
    write_log(log_path, records)
    return {'draft_id': draft_id, 'sent_request_count': len(keys)}


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
    # Unlinked history is independent evidence, never a slot for a new draft.
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
    duplicate.update({key: record[key] for key in CLAIM_FIELDS if key in record})
    duplicate.update({key: record[key] for key in EMAIL_GROUP_FIELDS if key in record})
    return duplicate


def duplicate_records_for_log_record(record: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    underlying = payload.get("underlying_requests") or record.get('underlying_requests') or []
    if not isinstance(underlying, list) or not underlying:
        return [build_duplicate_record(record)]

    records: list[dict[str, Any]] = []
    for item in underlying:
        if not isinstance(item, dict):
            continue
        child = dict(record)
        for key in CLAIM_FIELDS:
            child.pop(key, None)
        child.update({key: item[key] for key in CLAIM_FIELDS if key in item})
        # Packets historically use the packet PDF; source groups retain each separate request PDF.
        if record.get('email_grouping') in SEPARATE_PDF_GROUP_MODES:
            for key in ('pdf', 'pdf_sha256', 'draft_payload'):
                if not item.get(key):
                    raise ValueError(f'Source email group child is missing {key}.')
                child[key] = item[key]
            if record.get('email_grouping') == 'manual_visit':
                child.update({key: item[key] for key in MANUAL_VISIT_FIELDS if key in item})
        for key in ("case_number", "service_date", "service_period_label", "service_start_time", "service_end_time"):
            if key in {'service_period_label', 'service_start_time', 'service_end_time'}:
                child[key] = item.get(key, '')
            elif item.get(key) not in (None, ""):
                child[key] = item[key]
        records.append(build_duplicate_record(child))
    return records


def validate_superseded_request_coverage(requests: list[dict[str, Any]], records: list[dict[str, Any]], supersedes: list[str]) -> None:
    new_keys = {request_identity_key(row) for row in requests}
    known = {str(row.get('draft_id') or ''): row for row in records}
    for draft_id in supersedes:
        previous = known.get(draft_id)
        if not previous:
            raise ValueError('Correction references an unknown local draft ID.')
        if previous.get('status') == 'sent':
            raise ValueError('A sent draft cannot be superseded by a correction.')
        children = previous.get('underlying_requests') or [previous]
        if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
            raise ValueError('The draft being superseded has unclear request membership.')
        if not {request_identity_key(child) for child in children}.issubset(new_keys):
            raise ValueError('Correction must include every request in the grouped draft being superseded. Include its remaining cases before replacing that email.')


def validate_source_group_history(payload: dict[str, Any], records: list[dict[str, Any]], index: list[dict[str, Any]],
                                  *, draft_id: str, supersedes: list[str], reason: str, status: str = 'active') -> None:
    requests = payload.get('underlying_requests') or []
    validate_superseded_request_coverage(requests, records, supersedes)
    previous = next((row for row in records if row.get('draft_id') == draft_id), None)
    if previous and previous.get('status') not in {'active', 'drafted'} and status != previous.get('status'):
        raise ValueError('An already sent or retired group draft cannot be restored by an active recording retry.')
    if previous and (previous.get('email_grouping') != payload.get('email_grouping') or
                     previous.get('manual_visit_id') != payload.get('manual_visit_id') or
                     previous.get('email_group_id') != payload.get('email_group_id') or
                     previous.get('underlying_requests') != requests or previous.get('recipient') != payload.get('to')):
        raise ValueError('An existing draft ID cannot be rebound to different source email requests or PDFs.')
    request_keys = {request_identity_key(row) for row in requests}
    blocking = []
    for row in [*records, *index]:
        if row.get('draft_id') == draft_id or str(row.get('status') or 'sent') not in {'active', 'drafted', 'sent'}:
            continue
        children = row.get('underlying_requests') or [row]
        if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
            raise ValueError('A blocking history record has unclear request membership. Review that record before recording this email.')
        # A missing period on either side blocks every period of the same case/date,
        # matching the canonical app/CLI duplicate guard rather than exact-set lookup.
        child_keys = [request_identity_key(child) for child in children]
        if any(request_identity_keys_overlap(old, new) for old in child_keys for new in request_keys):
            blocking.append(row)
    if any(str(row.get('status') or 'sent') == 'sent' for row in blocking):
        raise ValueError('A grouped request is already sent. Stop before recording this email.')
    required = {str(row.get('draft_id') or '') for row in blocking}
    if required and ('' in required or not required.issubset(set(supersedes)) or len(reason.strip()) < 8):
        raise ValueError('A grouped request already has an active/drafted record. Use correction mode with a reason and every blocking draft ID before recording.')


def validate_record_history(record: dict[str, Any], payload: dict[str, Any], records: list[dict[str, Any]],
                            index: list[dict[str, Any]], child_records: list[dict[str, Any]]) -> None:
    """Keep every email mode bound to its original IDs and current history."""
    draft_id, status = record['draft_id'], record['status']
    previous_rows = [row for row in records if row.get('draft_id') == draft_id]
    if len(previous_rows) > 1:
        raise ValueError('This draft ID has conflicting local history. Review it before recording.')
    previous = previous_rows[0] if previous_rows else None
    requests = record.get('underlying_requests') or [record]
    validate_distinct_request_members(requests)
    keys = {request_identity_key(row) for row in requests}
    if previous:
        old_requests = previous.get('underlying_requests') or [previous]
        if (not isinstance(old_requests, list) or any(not isinstance(row, dict) for row in old_requests)
                or {request_identity_key(row) for row in old_requests} != keys
                or request_identity_key(previous) != request_identity_key(record)):
            raise ValueError('An existing draft ID cannot be rebound to different requests.')
        for field in ('message_id', 'thread_id', 'recipient', 'pdf', 'pdf_sha256'):
            if previous.get(field) and record.get(field) and previous[field] != record[field]:
                raise ValueError(f'An existing draft ID cannot be rebound to a different {field}.')
        if previous.get('draft_payload_sha256') and record.get('draft_payload'):
            if file_sha256(Path(record['draft_payload'])) != previous['draft_payload_sha256']:
                raise ValueError('The recorded draft payload changed. Restore the original before recording.')
        old_status = str(previous.get('status') or 'sent')
        if ((old_status == 'sent' and status != 'sent') or
                (old_status in {'trashed', 'superseded', 'not_found'} and status in {'active', 'sent'})):
            raise ValueError('An already sent or retired draft cannot be restored by an active recording retry.')
    children_by_key = {request_identity_key(row): row for row in child_records}
    linked = [row for row in index if row.get('draft_id') == draft_id]
    if len({request_identity_key(row) for row in linked}) != len(linked):
        raise ValueError('This draft ID has duplicate child history. Review it before recording.')
    for old in linked:
        child = children_by_key.get(request_identity_key(old))
        if child is None:
            raise ValueError('An existing draft ID cannot omit recorded request members.')
        if ((str(old.get('status') or 'sent') == 'sent' and status != 'sent') or
                (old.get('status') in {'trashed', 'superseded', 'not_found'} and status in {'active', 'sent'})):
            raise ValueError('An already sent or retired request cannot be restored by an active recording retry.')
        for field in ('message_id', 'thread_id', 'recipient_email', 'pdf', 'pdf_sha256'):
            if old.get(field) and child.get(field) and old[field] != child[field]:
                raise ValueError(f'An existing draft request cannot be rebound to a different {field}.')
    if status not in {'active', 'sent'}:
        return
    validate_superseded_request_coverage(requests, records, record['supersedes'])
    blocking = []
    for old in [*records, *index]:
        if old.get('draft_id') == draft_id or str(old.get('status') or 'sent') not in {'active', 'drafted', 'sent'}:
            continue
        members = old.get('underlying_requests') or [old]
        if not isinstance(members, list) or any(not isinstance(member, dict) for member in members):
            raise ValueError('A blocking history record has unclear request membership.')
        if any(request_identity_keys_overlap(request_identity_key(member), key) for member in members for key in keys):
            blocking.append(old)
    if any(str(row.get('status') or 'sent') == 'sent' for row in blocking):
        raise ValueError('A request is already sent. Stop before recording this email.')
    required = {str(row.get('draft_id') or '') for row in blocking}
    if required and ('' in required or not required.issubset(set(record['supersedes'])) or len(record['notes'].strip()) < 8):
        raise ValueError('A request already has an active/drafted record. Use correction mode with a reason and every blocking draft ID before recording.')


def validate_pending_record(log_path: Path, record: dict[str, Any], payload_path: Path | None) -> None:
    """Only the exact known result may finish an overlapping create reservation."""
    journal_path = log_path.with_name('gmail-create-attempts.local.json')
    if not journal_path.exists() or record['status'] not in {'active', 'sent'}:
        return
    journal = json.loads(journal_path.read_text(encoding='utf-8'))
    if not isinstance(journal, dict) or journal.get('schema_version') != 1 or not isinstance(journal.get('attempts'), list):
        raise ValueError('The Gmail attempt journal is invalid. Recover it before recording.')
    keys = {request_identity_key(row) for row in record.get('underlying_requests') or [record]}
    for attempt in journal['attempts']:
        if (not isinstance(attempt, dict) or not attempt.get('attempt_id') or not isinstance(attempt.get('requests'), list)
                or not attempt['requests'] or any(not isinstance(row, dict) for row in attempt['requests'])):
            raise ValueError('The Gmail attempt journal contains an invalid entry.')
        validate_distinct_request_members(attempt['requests'])
        if attempt.get('state') in {'recorded', 'not_created', 'confirmed_not_created'}:
            continue
        previous_keys = {request_identity_key(row) for row in attempt['requests']}
        if not any(request_identity_keys_overlap(old, new) for old in previous_keys for new in keys):
            continue
        result, target = attempt.get('gmail_result') or {}, attempt.get('target') or {}
        if (not isinstance(result, dict) or not isinstance(target, dict) or attempt.get('state') != 'created_unrecorded'
                or result.get('draft_id') != record['draft_id'] or result.get('message_id') != record['message_id']
                or (record.get('thread_id') and result.get('thread_id') and record['thread_id'] != result['thread_id'])
                or previous_keys != keys or not payload_path
                or str(payload_path.resolve()) != str(attempt.get('payload') or '')
                or not target.get('draft_payload_sha256')
                or file_sha256(payload_path) != target['draft_payload_sha256']):
            raise ValueError('Recover the pending Gmail attempt for these requests before recording another draft.')
        attachments, children = target.get('attachment_sha256', {}), target.get('child_payload_sha256', {})
        if not isinstance(attachments, dict) or not isinstance(children, dict):
            raise ValueError('The pending Gmail attempt has invalid original file bindings.')
        for raw, expected in {**attachments, **children}.items():
            if not Path(raw).is_file() or file_sha256(Path(raw)) != expected:
                raise ValueError('An original pending Gmail attachment or child payload changed. Restore it before recording.')


def _record_main(argv: list[str] | None = None) -> int:
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
        duplicate_records = load_duplicate_index(args.duplicate_index)
        previous = next((existing for existing in records if existing.get('draft_id') == args.draft_id), {})
        if previous and not payload:
            for field in ('service_period_label', 'service_start_time', 'service_end_time'):
                if getattr(args, field) is None:
                    record[field] = previous.get(field, '')
        # Bind future manual handoffs at initial recording; never authenticate a
        # legacy or edited payload retroactively during a status change.
        if previous:
            for field in ('created_at', 'draft_payload_sha256'):
                if previous.get(field):
                    record[field] = previous[field]
        elif args.status == 'active' and payload_path and payload_path.is_file():
            record['created_at'] = record['updated_at']
            record['draft_payload_sha256'] = file_sha256(payload_path)
        record.update({key: previous[key] for key in CLAIM_FIELDS if key in previous})
        record.update({key: payload[key] for key in CLAIM_FIELDS if key in payload})
        record.update({key: previous[key] for key in EMAIL_GROUP_FIELDS if key in previous})
        record.update({key: payload[key] for key in EMAIL_GROUP_FIELDS if key in payload})
        underlying = payload.get('underlying_requests') or previous.get('underlying_requests')
        if isinstance(underlying, list) and underlying:
            record['underlying_requests'] = underlying
        if payload and (args.status == 'active' or (args.status == 'sent' and not previous)):
            errors = validate_draft_payload(payload)
            if errors:
                raise ValueError('; '.join(errors))
        if payload:
            if (request_identity_key(record) != request_identity_key(payload)
                    or record['recipient'] != payload.get('to') or str(pdf_path) != str(Path(first_attachment_path(payload)).resolve())):
                raise ValueError('Draft record overrides do not match its payload.')
        if args.status in {'active', 'sent'}:
            validate_distinct_request_members(underlying if isinstance(underlying, list) and underlying else [record])
            if record.get('email_grouping') in SEPARATE_PDF_GROUP_MODES:
                if not payload:
                    raise ValueError('Source email group recording requires its reviewed payload.')
                errors = source_email_group_errors(payload)
                if errors:
                    raise ValueError('; '.join(errors))
                validate_source_group_history(payload, records, duplicate_records, draft_id=args.draft_id,
                                              supersedes=args.supersedes, reason=args.notes, status=args.status)
                if previous and str(previous.get('message_id') or '') != args.message_id:
                    raise ValueError('An existing group draft ID cannot be rebound to another message ID.')
                for key, value in (('case_number', record['case_number']), ('service_date', record['service_date']), ('to', record['recipient'])):
                    if str(payload.get(key) or '') != str(value):
                        raise ValueError('Source email group record overrides do not match its payload.')
            validate_travel_payload_groups(underlying if isinstance(underlying, list) and underlying else [record],
                                          prior_requests=recorded_travel_requests(records, duplicate_records))
        child_records = duplicate_records_for_log_record(record, payload)
        validate_record_history(record, payload, records, duplicate_records, child_records)
        validate_pending_record(args.log, record, payload_path)
        upsert_record(records, record)
        write_log(args.log, records)
        for duplicate_record in child_records:
            upsert_duplicate_record(duplicate_records, duplicate_record)
        write_duplicate_index(args.duplicate_index, duplicate_records)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Cannot record Gmail draft: {exc}", file=sys.stderr)
        return 2

    print(f"Recorded Gmail draft {args.draft_id} as {args.status}")
    return 0


def main(argv: list[str] | None = None, *, _attempt_lock_held: bool = False) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--help" in arguments or "-h" in arguments:
        return _record_main(arguments)
    lock_parser = argparse.ArgumentParser(add_help=False)
    lock_parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    selected, _ = lock_parser.parse_known_args(arguments)
    try:
        # Direct creation/recovery already owns the outer lock in this process.
        # Only trusted Python callers can skip reacquiring it, never CLI/JSON args.
        outer = contextlib.nullcontext() if _attempt_lock_held else state_file_lock(selected.log.with_name('.gmail-create-attempts.lock'))
        with outer, state_file_lock(selected.log.with_name(".gmail-history.lock")):
            return _record_main(arguments)
    except OSError as exc:
        print(f"Cannot record Gmail draft: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
