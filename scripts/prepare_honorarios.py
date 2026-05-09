from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

try:
    from scripts.build_email_draft import (
        DEFAULT_COURT_EMAILS,
        DEFAULT_EMAIL_CONFIG,
        build_email_payload,
        resolve_additional_attachments,
        resolve_recipient,
        validate_draft_payload,
    )
    from scripts.generate_pdf import (
        DEFAULT_DUPLICATE_INDEX,
        DEFAULT_HTML_DIR,
        DEFAULT_OUTPUT_DIR,
        DEFAULT_PROFILE,
        DEFAULT_TEMPLATE,
        IntakeError,
        build_rendered_request,
        default_output_path,
        find_duplicate_record,
        format_duplicate_message,
        format_numeric_date,
        generate_pdf,
        get_service_date_value,
        load_json,
        parse_iso_date,
        render_html,
        resolve_json_path,
        service_date_conflict,
    )
    from scripts.intake_questions import format_numbered_questions, missing_questions
    from scripts.request_identity import request_identity_key
    from scripts.source_classification import detect_translation_source, format_translation_rejection
except ModuleNotFoundError:
    from build_email_draft import (
        DEFAULT_COURT_EMAILS,
        DEFAULT_EMAIL_CONFIG,
        build_email_payload,
        resolve_additional_attachments,
        resolve_recipient,
        validate_draft_payload,
    )
    from generate_pdf import (
        DEFAULT_DUPLICATE_INDEX,
        DEFAULT_HTML_DIR,
        DEFAULT_OUTPUT_DIR,
        DEFAULT_PROFILE,
        DEFAULT_TEMPLATE,
        IntakeError,
        build_rendered_request,
        default_output_path,
        find_duplicate_record,
        format_duplicate_message,
        format_numeric_date,
        generate_pdf,
        get_service_date_value,
        load_json,
        parse_iso_date,
        render_html,
        resolve_json_path,
        service_date_conflict,
    )
    from intake_questions import format_numbered_questions, missing_questions
    from request_identity import request_identity_key
    from source_classification import detect_translation_source, format_translation_rejection


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAFT_OUTPUT_DIR = ROOT / "output" / "email-drafts"
DEFAULT_MANIFEST_DIR = ROOT / "output" / "manifests"
DEFAULT_RENDER_DIR = ROOT / "tmp" / "pdfs"
DEFAULT_DRAFT_LOG = ROOT / "data" / "gmail-draft-log.json"


def normalized_pdf_text(path: Path) -> str:
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    return " ".join(text.split())


def verify_pdf_text(path: Path, intake: dict[str, Any], rendered: Any) -> list[str]:
    text = normalized_pdf_text(path)
    service_date = parse_iso_date(get_service_date_value(intake), "service_date")
    expected = [
        rendered.case_number,
        format_numeric_date(service_date),
        rendered.addressee,
        rendered.service_paragraph,
    ]
    if rendered.transport_paragraph:
        expected.append(rendered.transport_paragraph)

    missing = [" ".join(item.split()) for item in expected if " ".join(item.split()) not in text]
    metadata_date = str(intake.get("photo_metadata_date") or "").strip()
    if metadata_date and metadata_date != get_service_date_value(intake):
        metadata_numeric = format_numeric_date(parse_iso_date(metadata_date, "photo_metadata_date"))
        if metadata_numeric in text:
            missing.append(f"unexpected metadata date in PDF: {metadata_numeric}")
    return missing


def render_png(pdf_path: Path, render_dir: Path) -> list[str]:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise IntakeError("pdftoppm is not available; cannot render PNG preview.")
    render_dir.mkdir(parents=True, exist_ok=True)
    prefix = render_dir / f"{pdf_path.stem}-render"
    result = subprocess.run(
        [pdftoppm, "-png", str(pdf_path), str(prefix)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise IntakeError(f"pdftoppm failed for {pdf_path}: {result.stderr.strip()}")
    return [str(path.resolve()) for path in sorted(render_dir.glob(f"{prefix.name}-*.png"))]


def load_draft_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise IntakeError(f"Draft log must be a list: {path}")
    return records


def active_drafts_for(intake: dict[str, Any], draft_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    case_number = str(intake.get("case_number") or "").strip()
    if not case_number:
        return []
    service_date = get_service_date_value(intake)
    intake_key = request_identity_key({
        "case_number": case_number,
        "service_date": service_date,
        "service_period_label": str(intake.get("service_period_label") or ""),
    })
    active: list[dict[str, Any]] = []
    for record in draft_log:
        if str(record.get("status") or "").strip() != "active":
            continue
        record_key = request_identity_key(record)
        if record_key[0] != intake_key[0] or record_key[1] != intake_key[1]:
            continue
        if intake_key[2] and record_key[2] and intake_key[2] != record_key[2]:
            continue
        active.append(record)
    return active


def validate_intake_before_generation(
    intake_path: Path,
    intake: dict[str, Any],
    *,
    profile: dict[str, Any],
    email_config: dict[str, Any],
    court_directory: list[dict[str, Any]],
    duplicate_index: Path,
    draft_log: list[dict[str, Any]],
    allow_duplicate: bool,
    allow_existing_draft: bool,
    correction_reason: str = "",
) -> tuple[str, str, str]:
    translation_matches = detect_translation_source(intake)
    if translation_matches:
        raise IntakeError(format_translation_rejection(translation_matches))

    questions = missing_questions(intake)
    if questions:
        raise IntakeError(f"Missing information in {intake_path}:\n{format_numbered_questions(questions)}")

    duplicate = find_duplicate_record(intake, duplicate_index)
    if duplicate and not allow_duplicate:
        raise IntakeError(format_duplicate_message(duplicate))

    active_drafts = active_drafts_for(intake, draft_log)
    if active_drafts and not allow_existing_draft:
        draft_ids = ", ".join(str(record.get("draft_id") or "") for record in active_drafts)
        raise IntakeError(
            "Active Gmail draft already recorded for this case number and service date. "
            f"Draft ID(s): {draft_ids}. Use --allow-existing-draft with --correction-reason only when correcting/replacing intentionally."
        )
    if active_drafts and allow_existing_draft and not str(correction_reason or "").strip():
        draft_ids = ", ".join(str(record.get("draft_id") or "") for record in active_drafts)
        raise IntakeError(
            "Correction reason required when using --allow-existing-draft over an active Gmail draft. "
            f"Draft ID(s): {draft_ids}. Add --correction-reason with a short audit reason."
        )

    build_rendered_request(intake, profile)
    resolve_recipient(intake, email_config, court_directory)
    additional_attachments = resolve_additional_attachments(intake)
    if additional_attachments and not str(intake.get("email_body") or "").strip():
        raise IntakeError("Additional attachments require a custom email_body that mentions the extra attachment(s).")

    return request_identity_key({
        "case_number": str(intake.get("case_number") or ""),
        "service_date": get_service_date_value(intake),
        "service_period_label": str(intake.get("service_period_label") or ""),
    })


def prepare_one(
    intake_path: Path,
    *,
    profile: dict[str, Any],
    email_config: dict[str, Any],
    court_directory: list[dict[str, Any]],
    template_path: Path,
    duplicate_index: Path,
    output_dir: Path,
    html_dir: Path,
    draft_output_dir: Path,
    render_dir: Path,
    draft_log: list[dict[str, Any]],
    allow_duplicate: bool,
    allow_existing_draft: bool,
    render_previews: bool,
    correction_reason: str = "",
) -> dict[str, Any]:
    intake = load_json(intake_path)

    questions = missing_questions(intake)
    if questions:
        raise IntakeError(f"Missing information in {intake_path}:\n{format_numbered_questions(questions)}")

    duplicate = find_duplicate_record(intake, duplicate_index)
    if duplicate and not allow_duplicate:
        raise IntakeError(format_duplicate_message(duplicate))

    active_drafts = active_drafts_for(intake, draft_log)
    if active_drafts and not allow_existing_draft:
        draft_ids = ", ".join(str(record.get("draft_id") or "") for record in active_drafts)
        raise IntakeError(
            "Active Gmail draft already recorded for this case number and service date. "
            f"Draft ID(s): {draft_ids}. Use --allow-existing-draft with --correction-reason only when correcting/replacing intentionally."
        )
    if active_drafts and allow_existing_draft and not str(correction_reason or "").strip():
        draft_ids = ", ".join(str(record.get("draft_id") or "") for record in active_drafts)
        raise IntakeError(
            "Correction reason required when using --allow-existing-draft over an active Gmail draft. "
            f"Draft ID(s): {draft_ids}. Add --correction-reason with a short audit reason."
        )

    rendered = build_rendered_request(intake, profile)
    pdf_path = output_dir / default_output_path(intake).name
    html_path = html_dir / f"{pdf_path.stem}.html"
    render_html(template_path, rendered, html_path)
    generate_pdf(rendered, pdf_path)

    missing = verify_pdf_text(pdf_path, intake, rendered)
    if missing:
        raise IntakeError(f"PDF verification failed for {pdf_path}: missing {missing}")

    payload = build_email_payload(intake, pdf_path, email_config, court_directory)
    payload_errors = validate_draft_payload(payload)
    if payload_errors:
        raise IntakeError(f"Draft payload is not Gmail-ready: {'; '.join(payload_errors)}")
    payload_path = draft_output_dir / f"{pdf_path.stem}.draft.json"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    png_previews = render_png(pdf_path, render_dir) if render_previews else []
    conflict = service_date_conflict(intake)
    transport = intake.get("transport") if isinstance(intake.get("transport"), dict) else {}

    result = {
        "intake": str(intake_path.resolve()),
        "source_filename": str(intake.get("source_filename") or "").strip(),
        "raw_case_number": str(intake.get("raw_case_number") or intake.get("source_case_number") or "").strip(),
        "canonical_case_number": rendered.case_number,
        "case_number": rendered.case_number,
        "service_date": get_service_date_value(intake),
        "service_date_source": str(intake.get("service_date_source") or ""),
        "photo_metadata_date": str(intake.get("photo_metadata_date") or "").strip(),
        "source_document_timestamp": str(intake.get("source_document_timestamp") or "").strip(),
        "service_period_label": str(intake.get("service_period_label") or "").strip(),
        "service_start_time": str(intake.get("service_start_time") or "").strip(),
        "service_end_time": str(intake.get("service_end_time") or "").strip(),
        "date_conflict": list(conflict) if conflict else None,
        "payment_entity": payload["payment_entity"],
        "service_entity": payload["service_entity"],
        "service_place": str(intake.get("service_place") or "").strip(),
        "entities_differ": bool(payload["entities_differ"]),
        "recipient": payload["to"],
        "subject": payload["subject"],
        "transport_destination": str(transport.get("destination") or "").strip(),
        "transport_km_one_way": transport.get("km_one_way", ""),
        "pdf": str(pdf_path.resolve()),
        "attachment_files": payload.get("attachment_file_list", payload["attachment_files"]),
        "attachment_count": len(payload.get("attachment_file_list", payload["attachment_files"])),
        "attachment_sha256": payload.get("attachment_sha256", {}),
        "html_preview": str(html_path.resolve()),
        "png_previews": png_previews,
        "png_preview_path": png_previews[0] if png_previews else "",
        "draft_payload": str(payload_path.resolve()),
        "gmail_tool": "_create_draft",
        "gmail_create_draft_args": payload["gmail_create_draft_args"],
        "draft_only": True,
        "send_allowed": False,
        "gmail_create_draft_ready": bool(payload.get("gmail_create_draft_ready", True)),
        "gmail_create_draft_blocker": str(payload.get("gmail_create_draft_blocker") or ""),
        "duplicate_checked": True,
        "duplicate_found": bool(duplicate),
        "active_gmail_drafts": [
            {
                "draft_id": record.get("draft_id", ""),
                "message_id": record.get("message_id", ""),
                "recipient": record.get("recipient", ""),
                "service_period_label": record.get("service_period_label", ""),
                "status": record.get("status", ""),
            }
            for record in active_drafts
        ],
    }
    if active_drafts and str(correction_reason or "").strip():
        result["correction_mode"] = True
        result["correction_reason"] = str(correction_reason or "").strip()
    return result


def print_summary(items: list[dict[str, Any]]) -> None:
    print(f"Prepared {len(items)} honorários request(s).")
    for item in items:
        print(
            " - "
            f"{item['case_number']} | service {item['service_date']} | "
            f"payment: {item['payment_entity']} | recipient: {item['recipient']} | "
            f"service place: {item['service_entity']}"
        )
        if item.get("service_period_label"):
            print(f"   Period: {item['service_period_label']} {item.get('service_start_time', '')}-{item.get('service_end_time', '')}".strip())
        print(f"   PDF: {item['pdf']}")
        attachments = item.get("attachment_files") or []
        if len(attachments) > 1:
            print(f"   Attachments: {len(attachments)} file(s)")
        if not item.get("gmail_create_draft_ready", True):
            print(f"   Gmail draft blocker: {item['gmail_create_draft_blocker']}")
        print(f"   Draft payload: {item['draft_payload']}")
    if all(item.get("gmail_create_draft_ready", True) for item in items):
        print("Next Gmail step: call _create_draft only for each payload, then record the returned draft IDs.")
    else:
        print("Next Gmail step: resolve the listed draft blocker before calling _create_draft.")


def default_manifest_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_MANIFEST_DIR / f"prepared-{timestamp}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare interpreting honorários PDFs and Gmail draft payloads in one checked batch."
    )
    parser.add_argument("intakes", nargs="+", type=Path, help="One or more intake JSON files.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--duplicate-index", type=Path, default=DEFAULT_DUPLICATE_INDEX)
    parser.add_argument("--email-config", type=Path, default=DEFAULT_EMAIL_CONFIG)
    parser.add_argument("--court-emails", type=Path, default=DEFAULT_COURT_EMAILS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--html-dir", type=Path, default=DEFAULT_HTML_DIR)
    parser.add_argument("--draft-output-dir", type=Path, default=DEFAULT_DRAFT_OUTPUT_DIR)
    parser.add_argument("--render-dir", type=Path, default=DEFAULT_RENDER_DIR)
    parser.add_argument("--draft-log", type=Path, default=DEFAULT_DRAFT_LOG)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--allow-duplicate", action="store_true")
    parser.add_argument("--allow-existing-draft", action="store_true", help="Allow preparing a case/date that already has an active draft in the local draft log.")
    parser.add_argument("--correction-reason", default="", help="Required audit reason when --allow-existing-draft is used to prepare a replacement.")
    parser.add_argument("--render-previews", action="store_true", help="Render PDF pages to PNG with pdftoppm.")
    args = parser.parse_args(argv)

    try:
        correction_reason = str(args.correction_reason or "").strip()
        if args.allow_existing_draft and not correction_reason:
            raise IntakeError("Correction reason required with --allow-existing-draft. Add --correction-reason with a short audit reason.")
        profile = load_json(args.profile)
        email_config = load_json(args.email_config)
        court_directory = json.loads(resolve_json_path(args.court_emails).read_text(encoding="utf-8"))
        draft_log = load_draft_log(args.draft_log)
        loaded: list[tuple[Path, dict[str, Any]]] = [(intake_path, load_json(intake_path)) for intake_path in args.intakes]
        seen_keys: dict[tuple[str, str, str], Path] = {}
        for intake_path, intake in loaded:
            key = validate_intake_before_generation(
                intake_path,
                intake,
                profile=profile,
                email_config=email_config,
                court_directory=court_directory,
                duplicate_index=args.duplicate_index,
                draft_log=draft_log,
                allow_duplicate=args.allow_duplicate,
                allow_existing_draft=args.allow_existing_draft,
                correction_reason=correction_reason,
            )
            if key in seen_keys:
                raise IntakeError(
                    "Duplicate request appears more than once in this batch: "
                    f"{intake_path} duplicates {seen_keys[key]}"
                )
            seen_keys[key] = intake_path

        items = [
            prepare_one(
                intake_path,
                profile=profile,
                email_config=email_config,
                court_directory=court_directory,
                template_path=args.template,
                duplicate_index=args.duplicate_index,
                output_dir=args.output_dir,
                html_dir=args.html_dir,
                draft_output_dir=args.draft_output_dir,
                render_dir=args.render_dir,
                draft_log=draft_log,
                allow_duplicate=args.allow_duplicate,
                allow_existing_draft=args.allow_existing_draft,
                render_previews=args.render_previews,
                correction_reason=correction_reason,
            )
            for intake_path in args.intakes
        ]
        manifest_path = args.manifest or default_manifest_path()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "draft_creation_tool": "_create_draft",
            "send_allowed": False,
            "correction_mode": bool(correction_reason),
            "correction_reason": correction_reason,
            "items": items,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (IntakeError, OSError, json.JSONDecodeError) as exc:
        print(f"Cannot prepare honorários batch: {exc}", file=sys.stderr)
        return 2

    print_summary(items)
    print(f"Manifest: {manifest_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
