from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

try:
    from scripts.entity_rules import build_service_place_clause, has_pj_host_building, normalize_text, resolve_entities, source_mentions_pj_context
    from scripts.request_identity import normalize_case_number, normalize_period_label
    from scripts.source_classification import detect_translation_source, format_translation_rejection
except ModuleNotFoundError:
    from entity_rules import build_service_place_clause, has_pj_host_building, normalize_text, resolve_entities, source_mentions_pj_context
    from request_identity import normalize_case_number, normalize_period_label
    from source_classification import detect_translation_source, format_translation_rejection


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "config" / "profile.json"
DEFAULT_TEMPLATE = ROOT / "templates" / "interprete_requerimento.html"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "pdf"
DEFAULT_HTML_DIR = ROOT / "tmp" / "pdfs"
DEFAULT_DUPLICATE_INDEX = ROOT / "data" / "duplicate-index.json"
BLOCKING_DUPLICATE_STATUSES = {"sent", "drafted"}

PORTUGUESE_MONTHS = {
    1: "janeiro",
    2: "fevereiro",
    3: "março",
    4: "abril",
    5: "maio",
    6: "junho",
    7: "julho",
    8: "agosto",
    9: "setembro",
    10: "outubro",
    11: "novembro",
    12: "dezembro",
}


class IntakeError(ValueError):
    """Raised when the intake is not ready for PDF generation."""


@dataclass
class RenderedRequest:
    case_number: str
    addressee: str
    applicant_name: str
    address: str
    service_paragraph: str
    transport_paragraph: str | None
    vat_irs_phrase: str
    payment_phrase: str
    iban: str
    closing_phrase: str
    closing_city: str
    closing_date_long: str
    signature_label: str
    signature_name: str


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f"Missing required field: {key}")
    return value.strip()


def parse_iso_date(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise IntakeError(f"{field_name} must use YYYY-MM-DD: {value}") from exc


def service_date_conflict(intake: dict[str, Any]) -> tuple[str, str] | None:
    service_date = str(intake.get("service_date") or "").strip()
    metadata_date = str(intake.get("photo_metadata_date") or "").strip()
    if service_date and metadata_date and service_date != metadata_date:
        return service_date, metadata_date
    return None


def service_date_conflict_is_confirmed(intake: dict[str, Any]) -> bool:
    source = str(intake.get("service_date_source") or "").strip().lower()
    return source in {
        "user_confirmed",
        "user_confirmed_exception",
        "document_text_user_confirmed",
        "photo_metadata_user_confirmed",
    }


def get_service_date_value(intake: dict[str, Any]) -> str:
    conflict = service_date_conflict(intake)
    if conflict and not service_date_conflict_is_confirmed(intake):
        service_date, metadata_date = conflict
        raise IntakeError(
            "Conflicting service dates found: "
            f"service_date={service_date}, photo_metadata_date={metadata_date}. "
            "Ask the user which date to use and set service_date_source to user_confirmed."
        )

    service_date = str(intake.get("service_date") or "").strip()
    if service_date:
        return service_date
    metadata_date = str(intake.get("photo_metadata_date") or "").strip()
    if metadata_date:
        return metadata_date
    raise IntakeError("Missing required field: service_date")


def format_numeric_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def format_long_date(value: date) -> str:
    return f"{value.day} de {PORTUGUESE_MONTHS[value.month]} de {value.year}"


def get_service_period_label(intake: dict[str, Any]) -> str:
    return str(intake.get("service_period_label") or "").strip()


def build_service_period_clause(intake: dict[str, Any]) -> str:
    start_time = str(intake.get("service_start_time") or "").strip()
    end_time = str(intake.get("service_end_time") or "").strip()
    if bool(start_time) != bool(end_time):
        raise IntakeError("service_start_time and service_end_time must be provided together.")
    if not start_time:
        return ""
    return f", no período das {start_time} às {end_time}"


def sanitize_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    safe = safe.replace("/", "-")
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "requerimento"


def duplicate_record_status(record: dict[str, Any]) -> str:
    status = str(record.get("status") or "").strip().lower()
    return status or "sent"


def duplicate_record_blocks(record: dict[str, Any]) -> bool:
    return duplicate_record_status(record) in BLOCKING_DUPLICATE_STATUSES


def load_duplicate_index(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        raise IntakeError(f"Duplicate index must be a list: {path}")
    return records


def find_duplicate_record(
    intake: dict[str, Any],
    index_path: Path = DEFAULT_DUPLICATE_INDEX,
    *,
    strict: bool = False,
) -> dict[str, Any] | None:
    case_number = str(intake.get("case_number") or "").strip()
    if not case_number:
        return None

    try:
        service_date_raw = get_service_date_value(intake)
    except IntakeError:
        if strict:
            raise
        return None

    service_date = parse_iso_date(service_date_raw, "service_date").isoformat()
    case_key = normalize_case_number(case_number)
    intake_period = normalize_period_label(get_service_period_label(intake))

    for record in load_duplicate_index(index_path):
        if not duplicate_record_blocks(record):
            continue
        record_case = str(record.get("case_number") or "")
        record_date = str(record.get("service_date") or "")
        if normalize_case_number(record_case) != case_key or record_date != service_date:
            continue
        record_period = normalize_period_label(get_service_period_label(record))
        if intake_period or record_period:
            if intake_period and record_period and intake_period != record_period:
                continue
        return record
    return None


def format_duplicate_message(record: dict[str, Any]) -> str:
    status = duplicate_record_status(record)
    details = [
        "Possible duplicate found before PDF generation.",
        f"Status: already {status}",
        f"Case number: {record.get('case_number', '')}",
        f"Service date: {record.get('service_date', '')}",
    ]
    if record.get("sent_date"):
        details.append(f"Already sent: {record['sent_date']}")
    if record.get("service_period_label"):
        details.append(f"Service period: {record['service_period_label']}")
    if record.get("draft_id"):
        details.append(f"Draft ID: {record['draft_id']}")
    if record.get("recipient_email"):
        details.append(f"Recipient: {record['recipient_email']}")
    elif record.get("recipient"):
        details.append(f"Recipient: {record['recipient']}")
    if record.get("source_filename"):
        details.append(f"Existing file: {record['source_filename']}")
    if record.get("pdf"):
        details.append(f"Existing PDF: {record['pdf']}")
    return "\n".join(details)


def build_transport_paragraph(intake: dict[str, Any], profile: dict[str, Any]) -> str | None:
    if not intake.get("claim_transport", False):
        return None

    transport = intake.get("transport")
    if not isinstance(transport, dict):
        raise IntakeError("Missing required field: transport")

    origin = str(transport.get("origin") or profile.get("default_origin") or "").strip()
    destination = str(transport.get("destination") or "").strip()
    km_one_way = transport.get("km_one_way")
    round_trip_phrase = str(transport.get("round_trip_phrase") or "ida_volta").strip()

    if not origin:
        raise IntakeError("Missing required field: transport.origin")
    if not destination:
        raise IntakeError("Missing required field: transport.destination")
    if km_one_way is None:
        raise IntakeError("Missing required field: transport.km_one_way")

    try:
        km = float(km_one_way)
    except (TypeError, ValueError) as exc:
        raise IntakeError("transport.km_one_way must be a number") from exc

    km_text = f"{km:g}"
    if round_trip_phrase == "cada_sentido":
        distance_text = f"{km_text} km em cada sentido"
    else:
        distance_text = f"{km_text} km para a ida e {km_text} km para a volta"

    return (
        "Mais requer o pagamento das despesas de transporte entre "
        f"{origin} e {destination}, tendo percorrido {distance_text}."
    )


def build_rendered_request(intake: dict[str, Any], profile: dict[str, Any]) -> RenderedRequest:
    translation_matches = detect_translation_source(intake)
    if translation_matches:
        raise IntakeError(format_translation_rejection(translation_matches))
    if source_mentions_pj_context(intake) and not has_pj_host_building(intake):
        raise IntakeError(
            "Polícia Judiciária interpreting requests must include the physical "
            "host building and city used for the service, for example "
            "Posto da GNR de Ferreira do Alentejo."
        )

    entities = resolve_entities(intake)
    if not entities["payment_entity"]:
        require_text(intake, "addressee")
    case_number = require_text(intake, "case_number")
    service_date = parse_iso_date(get_service_date_value(intake), "service_date")
    addressee = str(intake.get("addressee") or entities["payment_entity"]).strip()
    service_entity = str(entities["service_entity"]).strip()
    if not service_entity:
        service_entity = require_text(intake, "service_place")

    applicant_name = require_text(profile, "applicant_name")
    address = require_text(profile, "address")
    iban = require_text(profile, "iban")

    closing_city = str(intake.get("closing_city") or profile.get("default_closing_city") or "").strip()
    if not closing_city:
        raise IntakeError("Missing required field: closing_city")

    closing_date_raw = str(intake.get("closing_date") or "").strip()
    if closing_date_raw:
        closing_date = parse_iso_date(closing_date_raw, "closing_date")
    else:
        raise IntakeError("Missing required field: closing_date")

    service_place_clause = build_service_place_clause(intake, service_entity)
    service_period_clause = build_service_period_clause(intake)
    service_paragraph = (
        "Venho, por este meio, requerer o pagamento dos honorários devidos, "
        "em virtude de ter sido nomeado intérprete no âmbito do processo acima "
        f"identificado, no dia {format_numeric_date(service_date)}{service_period_clause}, "
        f"{service_place_clause}."
    )

    return RenderedRequest(
        case_number=case_number,
        addressee=addressee,
        applicant_name=applicant_name,
        address=address,
        service_paragraph=service_paragraph,
        transport_paragraph=build_transport_paragraph(intake, profile),
        vat_irs_phrase=require_text(profile, "vat_irs_phrase"),
        payment_phrase=require_text(profile, "payment_phrase"),
        iban=iban,
        closing_phrase=str(intake.get("closing_phrase") or profile.get("default_closing_phrase") or "Pede deferimento,").strip(),
        closing_city=closing_city,
        closing_date_long=format_long_date(closing_date),
        signature_label=str(profile.get("signature_label") or "O Requerente,").strip(),
        signature_name=str(profile.get("signature_name") or applicant_name).strip(),
    )


def render_html(template_path: Path, rendered: RenderedRequest, output_path: Path) -> None:
    template = template_path.read_text(encoding="utf-8")
    values = {
        "case_number": rendered.case_number,
        "addressee": html.escape(rendered.addressee).replace("\n", "<br>\n"),
        "applicant_name": rendered.applicant_name,
        "address": rendered.address,
        "service_paragraph": rendered.service_paragraph,
        "transport_paragraph": f"<p>{html.escape(rendered.transport_paragraph)}</p>" if rendered.transport_paragraph else "",
        "vat_irs_phrase": rendered.vat_irs_phrase,
        "payment_phrase": rendered.payment_phrase,
        "iban": rendered.iban,
        "closing_phrase": rendered.closing_phrase,
        "closing_city": rendered.closing_city,
        "closing_date_long": rendered.closing_date_long,
        "signature_label": rendered.signature_label,
        "signature_name": rendered.signature_name,
    }
    content = template
    for key, value in values.items():
        content = content.replace("{{ " + key + " }}", html.escape(str(value)) if key != "addressee" and key != "transport_paragraph" else str(value))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    escaped = html.escape(text).replace("\n", "<br/>")
    return Paragraph(escaped, style)


def generate_pdf(rendered: RenderedRequest, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=24 * mm,
        leftMargin=24 * mm,
        topMargin=28 * mm,
        bottomMargin=24 * mm,
        title="Requerimento de Honorários",
        author=rendered.applicant_name,
    )
    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "HonorariosBody",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=12,
        leading=17,
        spaceAfter=9,
    )
    process_style = ParagraphStyle(
        "Process",
        parent=base,
        spaceAfter=24,
    )
    block_style = ParagraphStyle(
        "Block",
        parent=base,
        spaceAfter=18,
    )

    story = [
        paragraph(f"Número de processo: {rendered.case_number}", process_style),
        paragraph(rendered.addressee, block_style),
        paragraph(f"Nome: {rendered.applicant_name}", base),
        paragraph(f"Morada: {rendered.address}", block_style),
        paragraph(rendered.service_paragraph, base),
    ]

    if rendered.transport_paragraph:
        story.append(paragraph(rendered.transport_paragraph, base))

    story.extend(
        [
            paragraph(rendered.vat_irs_phrase, base),
            paragraph(f"{rendered.payment_phrase} {rendered.iban}", block_style),
            Spacer(1, 26),
            paragraph(rendered.closing_phrase, base),
            paragraph(f"{rendered.closing_city}, {rendered.closing_date_long}", block_style),
            Spacer(1, 26),
            paragraph(rendered.signature_label, base),
            paragraph(rendered.signature_name, base),
        ]
    )

    doc.build(story)


def default_output_path(intake: dict[str, Any]) -> Path:
    case = sanitize_filename(str(intake.get("case_number", "requerimento")).replace("/", "-"))
    try:
        service_date_value = get_service_date_value(intake)
    except IntakeError:
        service_date_value = "sem-data"
    service_date = sanitize_filename(service_date_value)
    period_label = get_service_period_label(intake)
    if period_label:
        service_date = f"{service_date}_{sanitize_filename(period_label)}"
    return DEFAULT_OUTPUT_DIR / f"{case}_{service_date}.pdf"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an in-person interpreting honorários PDF.")
    parser.add_argument("intake", type=Path, help="Path to intake JSON.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE, help="Path to profile JSON.")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE, help="Path to HTML template.")
    parser.add_argument("--output", type=Path, default=None, help="Output PDF path.")
    parser.add_argument("--html-preview", type=Path, default=None, help="Optional rendered HTML preview path.")
    parser.add_argument("--duplicate-index", type=Path, default=DEFAULT_DUPLICATE_INDEX, help="Path to duplicate index JSON.")
    parser.add_argument("--allow-duplicate", action="store_true", help="Generate even when case number and service date already exist.")
    args = parser.parse_args(argv)

    try:
        intake = load_json(args.intake)
        if not args.allow_duplicate:
            duplicate = find_duplicate_record(intake, args.duplicate_index, strict=True)
            if duplicate:
                print(format_duplicate_message(duplicate), file=sys.stderr)
                return 3
        profile = load_json(args.profile)
        rendered = build_rendered_request(intake, profile)
        output_path = args.output or default_output_path(intake)
        html_preview = args.html_preview or DEFAULT_HTML_DIR / f"{output_path.stem}.html"
        render_html(args.template, rendered, html_preview)
        generate_pdf(rendered, output_path)
    except IntakeError as exc:
        print(f"Cannot generate PDF: {exc}", file=sys.stderr)
        return 2

    print(f"Generated PDF: {output_path}")
    print(f"Rendered HTML preview: {html_preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
