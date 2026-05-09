from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from scripts.generate_pdf import ROOT, IntakeError, resolve_json_path, sanitize_filename
except ModuleNotFoundError:
    from generate_pdf import ROOT, IntakeError, resolve_json_path, sanitize_filename


DEFAULT_SERVICE_PROFILES = ROOT / "data" / "service-profiles.json"
DEFAULT_OUTPUT_DIR = ROOT / "examples"
DEFAULT_TIMEZONE = "Europe/Lisbon"


def load_profiles(path: Path = DEFAULT_SERVICE_PROFILES) -> dict[str, Any]:
    resolved_path = resolve_json_path(path)
    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise IntakeError(f"Service profiles must be a JSON object: {resolved_path}")
    return data


def current_lisbon_date() -> str:
    try:
        return datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date().isoformat()
    except ZoneInfoNotFoundError:
        return datetime.now().date().isoformat()


def deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def remove_empty_values(data: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if value is None or value == "":
            continue
        if isinstance(value, dict):
            nested = remove_empty_values(value)
            if nested:
                cleaned[key] = nested
        elif isinstance(value, list):
            filtered = [item for item in value if item not in (None, "")]
            if filtered:
                cleaned[key] = filtered
        else:
            cleaned[key] = value
    return cleaned


def format_template(template: str, intake: dict[str, Any]) -> str:
    values = {
        "case_number": intake.get("case_number", ""),
        "service_date": intake.get("service_date", ""),
        "service_start_time": intake.get("service_start_time", ""),
        "service_end_time": intake.get("service_end_time", ""),
        "service_period_label": intake.get("service_period_label", ""),
    }
    return template.format(**values)


def normalize_attachment_args(values: list[str] | None) -> list[str]:
    return [str(value).strip() for value in values or [] if str(value).strip()]


def build_intake(
    *,
    profile_name: str,
    case_number: str,
    service_date: str,
    profiles: dict[str, Any],
    closing_date: str | None = None,
    service_date_source: str | None = None,
    service_period_label: str | None = None,
    service_start_time: str | None = None,
    service_end_time: str | None = None,
    raw_case_number: str | None = None,
    source_case_number: str | None = None,
    photo_metadata_date: str | None = None,
    source_document_timestamp: str | None = None,
    addressee: str | None = None,
    payment_entity: str | None = None,
    service_entity: str | None = None,
    service_entity_type: str | None = None,
    service_place: str | None = None,
    service_place_phrase: str | None = None,
    recipient_email: str | None = None,
    court_email_key: str | None = None,
    transport_destination: str | None = None,
    km_one_way: str | float | int | None = None,
    additional_attachment_files: list[str] | None = None,
    email_body: str | None = None,
    source_filename: str | None = None,
    source_text: str | None = None,
    notes: str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        available = ", ".join(sorted(profiles))
        raise IntakeError(f"Unknown service profile {profile_name!r}. Available profiles: {available}")

    defaults = profile.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise IntakeError(f"Profile defaults must be an object: {profile_name}")

    intake = copy.deepcopy(defaults)
    intake = deep_merge(intake, {
        "case_number": case_number.strip(),
        "service_date": service_date.strip(),
        "closing_date": closing_date or today or current_lisbon_date(),
    })

    optional_values = {
        "service_date_source": service_date_source,
        "service_period_label": service_period_label,
        "service_start_time": service_start_time,
        "service_end_time": service_end_time,
        "raw_case_number": raw_case_number,
        "source_case_number": source_case_number,
        "photo_metadata_date": photo_metadata_date,
        "source_document_timestamp": source_document_timestamp,
        "addressee": addressee,
        "payment_entity": payment_entity,
        "service_entity": service_entity,
        "service_entity_type": service_entity_type,
        "service_place": service_place,
        "service_place_phrase": service_place_phrase,
        "recipient_email": recipient_email,
        "court_email_key": court_email_key,
        "email_body": email_body,
        "source_filename": source_filename,
        "source_text": source_text,
        "notes": notes,
    }
    intake.update(remove_empty_values(optional_values))

    transport_overrides: dict[str, Any] = {}
    if transport_destination:
        transport_overrides["destination"] = transport_destination
    if km_one_way not in (None, ""):
        try:
            km_value = float(km_one_way)
            transport_overrides["km_one_way"] = int(km_value) if km_value.is_integer() else km_value
        except (TypeError, ValueError) as exc:
            raise IntakeError(f"--km-one-way must be numeric: {km_one_way}") from exc
    if transport_overrides:
        intake["transport"] = deep_merge(intake.get("transport") or {}, transport_overrides)

    attachments = normalize_attachment_args(additional_attachment_files)
    if attachments:
        intake["additional_attachment_files"] = attachments

    if not intake.get("source_text") and profile.get("source_text_template"):
        intake["source_text"] = format_template(str(profile["source_text_template"]), intake)
    if not intake.get("notes") and profile.get("notes_template"):
        intake["notes"] = format_template(str(profile["notes_template"]), intake)

    return remove_empty_values(intake)


def default_output_path(profile_name: str, intake: dict[str, Any]) -> Path:
    case = sanitize_filename(str(intake.get("case_number") or "requerimento").replace("/", "-"))
    service_date = sanitize_filename(str(intake.get("service_date") or "sem-data"))
    label = str(intake.get("service_period_label") or "").strip()
    if label:
        service_date = f"{service_date}_{sanitize_filename(label)}"
    safe_profile = re.sub(r"[^A-Za-z0-9._-]+", "-", profile_name).strip("-")
    return DEFAULT_OUTPUT_DIR / f"intake.{safe_profile}-{case}_{service_date}.example.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create an honorários intake JSON from a reusable service profile.")
    parser.add_argument("--profile", required=True, help="Service profile key from data/service-profiles.json.")
    parser.add_argument("--case-number", required=True, help="Case/process number.")
    parser.add_argument("--service-date", required=True, help="Service date in YYYY-MM-DD.")
    parser.add_argument("--service-date-source", help="Defaults to the profile value, usually user_confirmed.")
    parser.add_argument("--service-period-label", help="Optional label such as morning or afternoon.")
    parser.add_argument("--service-start-time", help="Optional start time, for example 10h00.")
    parser.add_argument("--service-end-time", help="Optional end time, for example 12h00.")
    parser.add_argument("--raw-case-number", help="Optional raw case number as visible in the source, including leading zeros.")
    parser.add_argument("--source-case-number", help="Optional source case number field when different from the normalized case number.")
    parser.add_argument("--photo-metadata-date", help="Visible phone/gallery metadata date in YYYY-MM-DD.")
    parser.add_argument("--source-document-timestamp", help="Visible printed/document timestamp, kept only for audit.")
    parser.add_argument("--addressee", help="Override the addressee block.")
    parser.add_argument("--payment-entity", help="Override the payment entity.")
    parser.add_argument("--service-entity", help="Override the service entity.")
    parser.add_argument("--service-entity-type", help="Override the service entity type.")
    parser.add_argument("--service-place", help="Override the physical service place.")
    parser.add_argument("--service-place-phrase", help="Override the service place phrase used in the PDF body.")
    parser.add_argument("--recipient-email", help="Override the recipient email.")
    parser.add_argument("--court-email-key", help="Known recipient key from data/court-emails.json.")
    parser.add_argument("--transport-destination", help="Override the transport destination.")
    parser.add_argument("--km-one-way", help="Override one-way kilometers from Marmelar.")
    parser.add_argument("--closing-date", help="Defaults to today's Europe/Lisbon date.")
    parser.add_argument("--source-filename", help="Optional source image/document filename.")
    parser.add_argument("--source-text", help="Optional extracted source text.")
    parser.add_argument("--notes", help="Optional notes.")
    parser.add_argument("--email-body", help="Optional custom email body for this request.")
    parser.add_argument("--additional-attachment-file", action="append", default=[], help="Optional supporting attachment path. Can be repeated.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_SERVICE_PROFILES, help="Path to service profile JSON.")
    parser.add_argument("--output", type=Path, help="Output intake path.")
    args = parser.parse_args(argv)

    try:
        profiles = load_profiles(args.profiles)
        intake = build_intake(
            profile_name=args.profile,
            case_number=args.case_number,
            service_date=args.service_date,
            profiles=profiles,
            closing_date=args.closing_date,
            service_date_source=args.service_date_source,
            service_period_label=args.service_period_label,
            service_start_time=args.service_start_time,
            service_end_time=args.service_end_time,
            raw_case_number=args.raw_case_number,
            source_case_number=args.source_case_number,
            photo_metadata_date=args.photo_metadata_date,
            source_document_timestamp=args.source_document_timestamp,
            addressee=args.addressee,
            payment_entity=args.payment_entity,
            service_entity=args.service_entity,
            service_entity_type=args.service_entity_type,
            service_place=args.service_place,
            service_place_phrase=args.service_place_phrase,
            recipient_email=args.recipient_email,
            court_email_key=args.court_email_key,
            transport_destination=args.transport_destination,
            km_one_way=args.km_one_way,
            additional_attachment_files=args.additional_attachment_file,
            email_body=args.email_body,
            source_filename=args.source_filename,
            source_text=args.source_text,
            notes=args.notes,
        )
        output = args.output or default_output_path(args.profile, intake)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(intake, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, IntakeError, ValueError) as exc:
        print(f"Cannot create intake: {exc}", file=sys.stderr)
        return 2

    print(f"Intake: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
