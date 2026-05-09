from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.entity_rules import normalize_text, resolve_entities
    from scripts.generate_pdf import ROOT, IntakeError, get_service_date_value, load_json, resolve_json_path
except ModuleNotFoundError:
    from entity_rules import normalize_text, resolve_entities
    from generate_pdf import ROOT, IntakeError, get_service_date_value, load_json, resolve_json_path


DEFAULT_EMAIL_CONFIG = ROOT / "config" / "email.json"
DEFAULT_COURT_EMAILS = ROOT / "data" / "court-emails.json"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "email-drafts"
COURT_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@tribunais\.org\.pt\b", re.IGNORECASE)
PAYLOAD_SCHEMA_VERSION = 1


def extract_court_emails(text: str) -> list[str]:
    seen: set[str] = set()
    emails: list[str] = []
    for match in COURT_EMAIL_RE.findall(text or ""):
        email = match.lower()
        if email not in seen:
            seen.add(email)
            emails.append(email)
    return emails


def compact_entity(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", normalize_text(value))
    ignored = {"a", "as", "de", "do", "dos", "da", "das", "e", "o", "os", "exmo", "exma", "senhor", "senhora"}
    return " ".join(token for token in tokens if token not in ignored)


def validate_explicit_email_fields(intake: dict[str, Any]) -> None:
    for key in ("court_email", "recipient_email"):
        value = str(intake.get(key) or "").strip()
        if value and not COURT_EMAIL_RE.fullmatch(value):
            raise IntakeError(f"{key} must be a tribunais.org.pt email address: {value}")


def find_directory_email(intake: dict[str, Any], directory: list[dict[str, Any]]) -> str | None:
    key = str(intake.get("court_email_key") or "").strip().lower()
    if not key:
        return None
    for record in directory:
        if str(record.get("key") or "").lower() == key:
            return str(record.get("email") or "").strip().lower()
    available = ", ".join(sorted(str(record.get("key") or "") for record in directory if record.get("key")))
    raise IntakeError(f"Unknown court_email_key: {key}. Available keys: {available}")


def expected_email_for_payment_entity(intake: dict[str, Any], directory: list[dict[str, Any]]) -> str | None:
    key = str(intake.get("court_email_key") or "").strip().lower()
    if key:
        return find_directory_email(intake, directory)

    payment_entity = str(intake.get("payment_entity") or intake.get("addressee") or "").strip()
    if not payment_entity:
        return None
    payment_key = compact_entity(payment_entity)
    if not payment_key:
        return None

    for record in directory:
        aliases = record.get("payment_entity_aliases") or []
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            alias_key = compact_entity(str(alias or ""))
            if alias_key and (alias_key == payment_key or alias_key in payment_key):
                email = str(record.get("email") or "").strip().lower()
                return email or None
    return None


def validate_recipient_consistency(intake: dict[str, Any], recipient: str, directory: list[dict[str, Any]]) -> None:
    expected = expected_email_for_payment_entity(intake, directory)
    if not expected or recipient == expected:
        return
    override_reason = str(
        intake.get("recipient_override_reason")
        or intake.get("court_email_override_reason")
        or ""
    ).strip()
    if override_reason:
        return
    payment_entity = str(intake.get("payment_entity") or intake.get("addressee") or "").strip()
    raise IntakeError(
        "Recipient does not match the payment entity. "
        f"Payment entity {payment_entity!r} maps to {expected}, but resolved recipient is {recipient}. "
        "If this is intentional, add recipient_override_reason."
    )


def resolve_recipient(intake: dict[str, Any], email_config: dict[str, Any], directory: list[dict[str, Any]]) -> tuple[str, str]:
    validate_explicit_email_fields(intake)
    source_text = "\n".join(
        str(intake.get(key) or "")
        for key in ("source_text", "notes", "addressee", "service_place")
    )
    extracted = extract_court_emails(source_text)
    if len(extracted) > 1:
        raise IntakeError(
            "Multiple court emails found in the source text. "
            "Set recipient_email or court_email_key after confirming the correct payment recipient."
        )
    if extracted:
        recipient = extracted[0]
        validate_recipient_consistency(intake, recipient, directory)
        return recipient, "source_text"

    for key in ("court_email", "recipient_email"):
        value = str(intake.get(key) or "").strip().lower()
        if value and COURT_EMAIL_RE.fullmatch(value):
            validate_recipient_consistency(intake, value, directory)
            return value, key

    directory_email = find_directory_email(intake, directory)
    if directory_email:
        validate_recipient_consistency(intake, directory_email, directory)
        return directory_email, "court_email_key"

    fallback = str(email_config.get("default_to") or "").strip().lower()
    if not fallback:
        raise IntakeError("Missing email default_to in config/email.json")
    validate_recipient_consistency(intake, fallback, directory)
    return fallback, "default_to"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_attachment_values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    raise IntakeError("additional_attachment_files must be a string or list of strings.")


def resolve_attachment_path(value: str) -> Path:
    raw = Path(value.strip())
    path = raw if raw.is_absolute() else ROOT / raw
    absolute = path.resolve()
    if not absolute.exists():
        raise IntakeError(f"Additional attachment does not exist: {absolute}")
    if not absolute.is_file():
        raise IntakeError(f"Additional attachment is not a file: {absolute}")
    return absolute


def resolve_additional_attachments(intake: dict[str, Any]) -> list[Path]:
    return [
        resolve_attachment_path(value)
        for value in normalize_attachment_values(intake.get("additional_attachment_files"))
    ]


def build_gmail_create_draft_args(recipient: str, subject: str, body: str, attachment_paths: list[str]) -> dict[str, Any]:
    return {
        "to": recipient,
        "subject": subject,
        "body": body,
        "attachment_files": attachment_paths,
    }


def attachment_array_errors(value: Any, field_name: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list):
        return [f"{field_name} must be an array of absolute existing file paths."]
    if not value:
        errors.append(f"{field_name} must include at least one attachment.")
    for item in value:
        text = str(item or "").strip()
        if not text:
            errors.append(f"{field_name} contains an empty attachment path.")
            continue
        path = Path(text)
        if not path.is_absolute():
            errors.append(f"{field_name} contains a relative attachment path: {text}")
            continue
        if not path.exists():
            errors.append(f"{field_name} attachment does not exist: {text}")
        elif not path.is_file():
            errors.append(f"{field_name} attachment is not a file: {text}")
    return errors


def validate_draft_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("gmail_tool") != "_create_draft":
        errors.append("gmail_tool must be _create_draft.")
    if payload.get("draft_only") is not True:
        errors.append("draft_only must be true.")
    if payload.get("send_allowed") is not False:
        errors.append("send_allowed must be false.")
    if payload.get("gmail_create_draft_ready") is not True:
        blocker = str(payload.get("gmail_create_draft_blocker") or "").strip()
        errors.append(f"gmail_create_draft_ready must be true before Gmail draft creation.{f' Blocker: {blocker}' if blocker else ''}")

    attachment_files = payload.get("attachment_files")
    errors.extend(attachment_array_errors(attachment_files, "attachment_files"))

    args = payload.get("gmail_create_draft_args")
    if not isinstance(args, dict):
        errors.append("gmail_create_draft_args is missing or not an object.")
        return errors

    for field in ("to", "subject", "body"):
        if not str(args.get(field) or "").strip():
            errors.append(f"gmail_create_draft_args.{field} is required.")
    args_attachments = args.get("attachment_files")
    errors.extend(attachment_array_errors(args_attachments, "gmail_create_draft_args.attachment_files"))
    if isinstance(attachment_files, list) and isinstance(args_attachments, list):
        if [str(item) for item in args_attachments] != [str(item) for item in attachment_files]:
            errors.append("gmail_create_draft_args.attachment_files must match attachment_files.")
    return errors


def build_email_payload(intake: dict[str, Any], pdf_path: Path, email_config: dict[str, Any], directory: list[dict[str, Any]]) -> dict[str, Any]:
    recipient, recipient_source = resolve_recipient(intake, email_config, directory)
    absolute_pdf = pdf_path.resolve()
    if not absolute_pdf.exists():
        raise IntakeError(f"PDF attachment does not exist: {absolute_pdf}")
    entities = resolve_entities(intake)
    additional_attachments = resolve_additional_attachments(intake)
    attachment_paths = [absolute_pdf]
    for attachment in additional_attachments:
        if attachment not in attachment_paths:
            attachment_paths.append(attachment)
    attachment_path_strings = [str(path) for path in attachment_paths]
    attachment_hashes = {str(path): file_sha256(path) for path in attachment_paths}
    subject = str(email_config.get("subject") or "Requerimento de honorários")
    body = str(intake.get("email_body") or email_config.get("body") or "")
    has_custom_body = bool(str(intake.get("email_body") or "").strip())
    gmail_create_draft_ready = True
    gmail_create_draft_blocker = ""
    if additional_attachments and not has_custom_body:
        gmail_create_draft_ready = False
        gmail_create_draft_blocker = "Additional attachments require a custom email_body that mentions the extra attachment(s)."
    gmail_create_draft_args = build_gmail_create_draft_args(recipient, subject, body, attachment_path_strings)
    payload = {
        "payload_schema_version": PAYLOAD_SCHEMA_VERSION,
        "gmail_tool": "_create_draft",
        "case_number": str(intake.get("case_number") or "").strip(),
        "service_date": get_service_date_value(intake),
        "service_period_label": str(intake.get("service_period_label") or "").strip(),
        "service_start_time": str(intake.get("service_start_time") or "").strip(),
        "service_end_time": str(intake.get("service_end_time") or "").strip(),
        "payment_entity": entities["payment_entity"],
        "service_entity": entities["service_entity"],
        "service_entity_type": entities["service_entity_type"],
        "entities_differ": entities["entities_differ"],
        "to": recipient,
        "recipient_source": recipient_source,
        "subject": subject,
        "body": body,
        "attachment_files": attachment_path_strings,
        "attachment_file_list": attachment_path_strings,
        "additional_attachment_files": [str(path) for path in attachment_paths[1:]],
        "attachment_basename": absolute_pdf.name,
        "attachment_basenames": [path.name for path in attachment_paths],
        "pdf_sha256": file_sha256(absolute_pdf),
        "attachment_sha256": attachment_hashes,
        "gmail_create_draft_args": gmail_create_draft_args,
        "payload_created_at": datetime.now(timezone.utc).isoformat(),
        "draft_only": True,
        "send_allowed": False,
        "gmail_create_draft_ready": gmail_create_draft_ready,
        "gmail_create_draft_blocker": gmail_create_draft_blocker,
        "safety_note": "Create a Gmail draft only. Do not send unless the user explicitly asks after reviewing.",
    }
    if isinstance(intake.get("underlying_requests"), list):
        payload["underlying_requests"] = intake["underlying_requests"]
    return payload


def default_output_path(pdf_path: Path) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{pdf_path.stem}.draft.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Gmail draft payload for a generated honorários PDF.")
    parser.add_argument("intake", type=Path, help="Path to intake JSON.")
    parser.add_argument("--pdf", required=True, type=Path, help="Generated PDF to attach.")
    parser.add_argument("--email-config", type=Path, default=DEFAULT_EMAIL_CONFIG, help="Path to email config JSON.")
    parser.add_argument("--court-emails", type=Path, default=DEFAULT_COURT_EMAILS, help="Path to known court email directory.")
    parser.add_argument("--output", type=Path, help="Output draft payload JSON path.")
    args = parser.parse_args(argv)

    try:
        intake = load_json(args.intake)
        email_config = load_json(args.email_config)
        directory = json.loads(resolve_json_path(args.court_emails).read_text(encoding="utf-8"))
        payload = build_email_payload(intake, args.pdf, email_config, directory)
        output_path = args.output or default_output_path(args.pdf)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (IntakeError, OSError, json.JSONDecodeError) as exc:
        print(f"Cannot build Gmail draft payload: {exc}", file=sys.stderr)
        return 2

    print(f"Draft payload: {output_path}")
    print(f"To: {payload['to']}")
    print(f"Subject: {payload['subject']}")
    print("Gmail action: _create_draft only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
