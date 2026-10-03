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
    from scripts.generate_pdf import ROOT, DEFAULT_PROFILE, IntakeError, get_service_date_value, load_json, resolve_json_path
    from scripts.claim_options import ClaimError, claim_metadata, profile_binding, validate_claims, validate_travel_payload_groups
    from scripts.request_identity import validate_distinct_request_members
except ModuleNotFoundError:
    from entity_rules import normalize_text, resolve_entities
    from generate_pdf import ROOT, DEFAULT_PROFILE, IntakeError, get_service_date_value, load_json, resolve_json_path
    from claim_options import ClaimError, claim_metadata, profile_binding, validate_claims, validate_travel_payload_groups
    from request_identity import validate_distinct_request_members


DEFAULT_EMAIL_CONFIG = ROOT / "config" / "email.json"
DEFAULT_COURT_EMAILS = ROOT / "data" / "court-emails.json"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "email-drafts"
COURT_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@tribunais\.org\.pt\b", re.IGNORECASE)
PAYLOAD_SCHEMA_VERSION = 1
SEPARATE_PDF_GROUP_MODES = {'source', 'manual_visit'}
MANUAL_VISIT_FIELDS = ('manual_visit_id', 'manual_visit_provenance', 'source_kind', 'service_place', 'payment_entity')


def manual_visit_member_errors(payload: dict[str, Any], member: dict[str, Any]) -> list[str]:
    """Pure declaration/visit checks, shared with bounded sent reconciliation."""
    errors: list[str] = []
    visit_id = str(payload.get('manual_visit_id') or '')
    if not re.fullmatch(r'manual-visit-[a-f0-9]{64}', visit_id):
        errors.append('Manual visit requires its bounded derived manual_visit_id.')
    for row in (payload, member):
        if (row.get('manual_visit_id') != visit_id or row.get('manual_visit_provenance') != 'user_declared_manual_visit'
                or row.get('source_kind') != 'manual_review'
                or any(str(row.get(key) or '').strip() for key in ('source_sha256', 'source_file', 'source_filename'))):
            errors.append('Manual visit requires an explicit manual declaration without photo/source provenance.')
            break
    recipient = str(payload.get('to') or payload.get('recipient') or '').strip().lower()
    member_recipient = str(member.get('to') or member.get('recipient') or '').strip().lower()
    for key in ('service_date', 'personal_profile_id'):
        value = str(payload.get(key) or '').strip()
        if not value or str(member.get(key) or '').strip() != value:
            errors.append(f'Manual visit child has a conflicting or missing {key}.')
    for key in ('service_place', 'payment_entity'):
        value = ' '.join(normalize_text(str(payload.get(key) or '')).split())
        other = ' '.join(normalize_text(str(member.get(key) or '')).split())
        if not value or other != value:
            errors.append(f'Manual visit child has a conflicting or missing {key}.')
    if not recipient or member_recipient != recipient:
        errors.append('Manual visit child has a conflicting or missing recipient.')
    if member.get('travel_group_id') != visit_id:
        errors.append('Manual visit child must retain its declared travel group.')
    binding = member.get('travel_group_binding')
    if (not isinstance(binding, list) or len(binding) != 5
            or binding[0] != member.get('service_date') or binding[3] != member.get('personal_profile_id')
            or ' '.join(normalize_text(str(binding[1])).split()) != ' '.join(normalize_text(str(member.get('service_place') or '')).split())):
        errors.append('Manual visit child trip binding differs from its physical visit metadata.')
    return errors


def manual_visit_group_metadata_errors(payload: dict[str, Any], children: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if len(children) < 2:
        errors.append('Manual visit email requires at least two reviewed requests.')
    for member in children:
        errors.extend(manual_visit_member_errors(payload, member))
    if sum(member.get('claim_transport') is True for member in children) != 1:
        errors.append('Manual visit requires exactly one travel-bearing request.')
    try:
        validate_travel_payload_groups(children)
    except ValueError as exc:
        errors.append(str(exc))
    return errors


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
    matches = {str(record.get('email') or '').strip().lower() for record in directory
               if str(record.get('key') or '').strip().lower() == key}
    if matches:
        if len(matches) != 1 or not next(iter(matches)):
            raise IntakeError('Selected court_email_key has conflicting or missing saved emails. Correct that saved contact before preparing.')
        return next(iter(matches))
    available = ", ".join(sorted(str(record.get("key") or "") for record in directory if record.get("key")))
    raise IntakeError(f"Unknown court_email_key: {key}. Available keys: {available}")


def expected_email_for_payment_entity(intake: dict[str, Any], directory: list[dict[str, Any]]) -> str | None:
    # A selected key is a recipient choice, not evidence of the independent payer.
    payment_entity = str(intake.get("payment_entity") or intake.get("addressee") or "").strip()
    if not payment_entity:
        return None
    payment_key = compact_entity(payment_entity)
    if not payment_key:
        return None

    matches: list[tuple[tuple[bool, int], str]] = []
    for record in directory:
        aliases = record.get("payment_entity_aliases") or []
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            alias_key = compact_entity(str(alias or ""))
            if alias_key and f' {alias_key} ' in f' {payment_key} ':
                email = str(record.get("email") or "").strip().lower()
                matches.append(((alias_key == payment_key, len(alias_key.split())), email))
    if not matches:
        return None
    best = max(score for score, _email in matches)
    emails = {email for score, email in matches if score == best}
    if len(emails) != 1 or not next(iter(emails)):
        raise IntakeError('The paying court matches conflicting or incomplete saved contacts. Specify the local paying court, correct the contact aliases, or confirm an intentional recipient_override_reason with an explicit recipient.')
    return next(iter(emails))


def validate_recipient_consistency(intake: dict[str, Any], recipient: str, directory: list[dict[str, Any]]) -> None:
    override_reason = str(
        intake.get("recipient_override_reason")
        or intake.get("court_email_override_reason")
        or ""
    ).strip()
    if override_reason:
        return
    expected = expected_email_for_payment_entity(intake, directory)
    if not expected or recipient == expected:
        return
    payment_entity = str(intake.get("payment_entity") or intake.get("addressee") or "").strip()
    raise IntakeError(
        "Recipient does not match the payment entity. "
        f"Payment entity {payment_entity!r} maps to {expected}, but resolved recipient is {recipient}. "
        "If this is intentional, add recipient_override_reason."
    )


def resolve_recipient(intake: dict[str, Any], email_config: dict[str, Any], directory: list[dict[str, Any]]) -> tuple[str, str]:
    validate_explicit_email_fields(intake)
    selected = [(key, str(intake.get(key) or '').strip().lower()) for key in ('recipient_email', 'court_email')
                if str(intake.get(key) or '').strip()]
    directory_email = find_directory_email(intake, directory)
    if directory_email:
        selected.append(('court_email_key', directory_email))
    # An explicit selection resolves footer ambiguity, but each populated choice
    # must still agree with the independent payer unless intentionally overridden.
    for _key, recipient in selected:
        validate_recipient_consistency(intake, recipient, directory)
    if selected:
        override_reason = str(intake.get('recipient_override_reason') or intake.get('court_email_override_reason') or '').strip()
        if len({recipient for _key, recipient in selected}) > 1 and not override_reason:
            raise IntakeError('Explicit recipient fields and selected saved contact disagree. Clear the old contact or choose matching recipient fields before preparing.')
        return selected[0][1], selected[0][0]
    photo_policy = intake.get("photo_defaults_applied")
    if isinstance(photo_policy, dict) and "routing_status" in photo_policy:
        # A chosen city-court default/manual exception outranks unrelated source
        # footer contacts. Never resurrect the generic email fallback here.
        raise IntakeError("The photo-city court recipient is missing. Enter the paying court's verified email address.")
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

    payer_email = expected_email_for_payment_entity(intake, directory)
    if payer_email:
        return payer_email, 'payment_entity_directory'

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
    subject = validate_email_subject(subject)
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
    if payload.get('email_grouping') in SEPARATE_PDF_GROUP_MODES:
        errors.extend(source_email_group_errors(payload))
    try:
        children = payload.get('underlying_requests')
        if isinstance(children, list) and children:
            validate_distinct_request_members(children)
        validate_travel_payload_groups(children if isinstance(children, list) and children else [payload])
    except ValueError as exc:
        errors.append(str(exc))
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
    try:
        validate_email_subject(args.get('subject'))
    except IntakeError as exc:
        errors.append(str(exc))
    args_attachments = args.get("attachment_files")
    errors.extend(attachment_array_errors(args_attachments, "gmail_create_draft_args.attachment_files"))
    if isinstance(attachment_files, list) and isinstance(args_attachments, list):
        if [str(item) for item in args_attachments] != [str(item) for item in attachment_files]:
            errors.append("gmail_create_draft_args.attachment_files must match attachment_files.")
    return errors


def source_email_group_errors(payload: dict[str, Any]) -> list[str]:
    """Check each grouped child before transport or either history file is written."""
    errors: list[str] = []
    children = payload.get('underlying_requests')
    if not isinstance(children, list) or not children:
        return ['Source email group requires a nonempty underlying_requests array.']
    try:
        validate_distinct_request_members(children)
    except ValueError as exc:
        errors.append(str(exc))
    if not str(payload.get('email_group_id') or '').strip():
        errors.append('Source email group requires email_group_id.')
    source_hash = str(payload.get('source_sha256') or '')
    manual_visit = payload.get('email_grouping') == 'manual_visit'
    if manual_visit:
        errors.extend(manual_visit_group_metadata_errors(payload, [child for child in children if isinstance(child, dict)]))
    profile = str(payload.get('personal_profile_id') or '')
    recipient = str(payload.get('to') or '').strip().lower()
    child_paths = payload.get('child_payload_paths')
    if not isinstance(child_paths, list) or len(child_paths) != len(children):
        errors.append('Source email group must retain one child_payload_path per request.')
        child_paths = []
    attachments = payload.get('attachment_files')
    attachment_hashes = payload.get('attachment_sha256')
    if not isinstance(attachments, list) or not all(isinstance(path, str) for path in attachments) or not isinstance(attachment_hashes, dict):
        return errors + ['Source email group requires attachment_files array and attachment_sha256 object.']
    identities: set[tuple[str, str, str]] = set()
    pdfs: set[str] = set()
    for index, child in enumerate(children):
        if not isinstance(child, dict):
            errors.append(f'Source email group child {index + 1} must be an object.')
            continue
        identity = (str(child.get('case_number') or '').strip(), str(child.get('service_date') or '').strip(), str(child.get('service_period_label') or '').strip())
        if not identity[0] or not identity[1] or identity in identities:
            errors.append(f'Source email group child {index + 1} has a missing or repeated request identity.')
        identities.add(identity)
        if (str(child.get('source_sha256') or '') != source_hash or
                str(child.get('personal_profile_id') or '') != profile or
                str(child.get('recipient') or '').strip().lower() != recipient):
            errors.append(f'Source email group child {index + 1} has conflicting source, profile, or recipient.')
        try:
            raw_pdf = str(child.get('pdf') or '')
            raw_payload = str(child.get('draft_payload') or '')
            if not raw_pdf or not raw_payload:
                raise ValueError('missing child PDF/payload path')
            pdf = Path(raw_pdf).resolve()
            child_path = Path(raw_payload).resolve()
            expected = str(child.get('pdf_sha256') or '')
            if str(pdf) in pdfs or str(pdf) not in attachments or not expected or file_sha256(pdf) != expected or attachment_hashes.get(str(pdf)) != expected:
                raise ValueError('missing, repeated, changed, or unattached child PDF')
            pdfs.add(str(pdf))
            if index >= len(child_paths) or str(child_path) != child_paths[index]:
                raise ValueError('child payload order does not match requests')
            if file_sha256(child_path) != str(child.get('draft_payload_sha256') or ''):
                raise ValueError('child payload changed')
            data = json.loads(child_path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or any(str(data.get(key) or '').strip() != identity[position] for position, key in enumerate(('case_number', 'service_date', 'service_period_label'))):
                raise ValueError('child payload request identity changed')
            hashes = data.get('attachment_sha256')
            if str(data.get('to') or '').strip().lower() != recipient or str(pdf) not in (data.get('attachment_files') or []) or not isinstance(hashes, dict) or hashes.get(str(pdf)) != expected:
                raise ValueError('child payload recipient or PDF changed')
            if data.get('draft_only') is not True or data.get('send_allowed') is not False or data.get('gmail_create_draft_ready') is not True:
                raise ValueError('child payload is not draft-ready')
            for key in ('claim_interpreting', 'claim_transport', 'travel_group_id', 'travel_group_binding'):
                if child.get(key) != data.get(key):
                    raise ValueError('child claim metadata changed')
            if manual_visit:
                metadata_errors = manual_visit_member_errors(payload, data)
                if metadata_errors or any(child.get(key) != data.get(key) for key in MANUAL_VISIT_FIELDS):
                    raise ValueError('child manual-visit declaration or physical-visit metadata changed')
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f'Source email group child {index + 1} is stale or invalid: {exc}. Prepare the group again.')
    return errors


def source_email_body(intakes: list[dict[str, Any]], *, signature_name: str) -> str:
    if len(intakes) > 1:
        require_individual_email_text(intakes, mode='Source email grouping')
    fee = any(intake.get('claim_interpreting', True) for intake in intakes)
    travel = any(intake.get('claim_transport', False) for intake in intakes)
    scope = ('honorários e despesas de transporte' if travel else 'honorários') if fee else 'despesas de transporte'
    return ('Bom dia,\n\n'
            f'Venho por este meio requerer o pagamento de {scope}, conforme os pedidos individuais anexos.\n\n'
            f'Poderão encontrar em anexo {len(intakes)} requerimentos, cada um num ficheiro PDF separado.\n\n'
            f'Melhores cumprimentos,\n\n{signature_name}')


def require_individual_email_text(intakes: list[dict[str, Any]], *, mode: str) -> None:
    if any(str(intake.get(field) or '').strip() for intake in intakes for field in ('email_subject', 'email_body')):
        raise IntakeError(f'{mode} cannot replace a custom per-request email_subject or email_body. Choose individual emails to retain that text.')


def validate_email_subject(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntakeError('Email subject must be nonempty text.')
    if len(value) > 2048 or any(ord(char) < 32 or 127 <= ord(char) <= 159 or char in '\u2028\u2029' for char in value):
        raise IntakeError('Email subject must be a single line of at most 2048 characters, without control characters.')
    return value.strip()


def resolve_email_subject(intake: dict[str, Any], email_config: dict[str, Any]) -> str:
    custom = intake.get('email_subject')
    if custom is not None and not isinstance(custom, str):
        raise IntakeError('Email subject must be text.')
    # Validate before trimming: even a whitespace-only header must not hide CR/LF.
    if custom and (custom.strip() or any(char != ' ' for char in custom)):
        subject = validate_email_subject(custom)
        if intake.get('claim_interpreting', True) is False and (re.search(r'\bhonorarios\b', normalize_text(subject)) or custom_transport_body_conflict(subject)):
            raise IntakeError('Travel-only email_subject must request only transport, not interpreting fees.')
        return subject
    default = 'Requerimento de despesas de transporte' if intake.get('claim_interpreting', True) is False else email_config.get('subject') or 'Requerimento de honorários'
    return validate_email_subject(default)


def resolve_email_body(intake: dict[str, Any], email_config: dict[str, Any], *, signature_name: str = "") -> str:
    try:
        interpreting, transport = validate_claims(intake)
    except ClaimError as exc:
        raise IntakeError(str(exc)) from exc
    # A request-specific body remains verbatim. Configured bodies opt into the
    # selected PDF signature only by containing this exact template token.
    if str(intake.get("email_body") or '').strip():
        body = str(intake["email_body"])
        if not interpreting and custom_transport_body_conflict(body):
            raise IntakeError('Travel-only email_body requests interpreting fees or asserts performed interpreting. Edit the custom body to request only transport, or change the claim choice.')
        return body
    if not interpreting and transport:
        signature = str(signature_name or '').strip()
        if not signature:
            raise IntakeError('The travel-only email requires the selected profile signature_name.')
        return ('Bom dia,\n\nVenho por este meio requerer o pagamento das despesas de transporte '
                'relativas à minha comparência na qualidade de intérprete.\n\n'
                'Poderão encontrar o requerimento de despesas de transporte em anexo.\n\n'
                f'Melhores cumprimentos,\n\n{signature}')
    body = str(email_config.get("body") or "")
    if "{{signature_name}}" in body:
        signature = str(signature_name or "").strip()
        if not signature:
            raise IntakeError("The email body template requires the selected profile signature_name.")
        return body.replace("{{signature_name}}", signature)
    return body


def custom_transport_body_conflict(body: str) -> bool:
    for sentence in re.split(r'[.!?\n]+', normalize_text(body)):
        # Remove only an explicitly negated fee/work clause, never a whole sentence.
        sentence = re.sub(r'\bnao\s+(?:requeiro|solicito|reclamo)\s+(?:o\s+)?(?:pagamento\s+(?:de|dos)\s+)?honorarios(?:\s+devidos)?', '', sentence)
        sentence = re.sub(r'\bnao\s+prestei\s+(?:o\s+)?(?:servico\s+de\s+)?interpretacao\b', '', sentence)
        if re.search(r'\b(?:pagamento|requerer|requeiro|solicito|solicitar)\b[^.!?\n]{0,120}\bhonorarios\b', sentence):
            return True
        if re.search(r'\bhonorarios\s+devidos\b|\bprestei\s+(?:o\s+)?(?:servico\s+de\s+)?interpretacao\b', sentence):
            return True
        if re.search(r'\b(?:servico\s+de\s+interpretacao|diligencia)\b[^.!?\n]{0,60}\b(?:realizad[oa]|prestad[oa])\b', sentence):
            return True
    return False


def build_email_payload(intake: dict[str, Any], pdf_path: Path, email_config: dict[str, Any], directory: list[dict[str, Any]], *, signature_name: str = "", personal_profile_key: str = "") -> dict[str, Any]:
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
    subject = resolve_email_subject(intake, email_config)
    body = resolve_email_body(intake, email_config, signature_name=signature_name)
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
    try:
        payload.update(claim_metadata(intake, personal_profile_key=personal_profile_key))
    except ClaimError as exc:
        raise IntakeError(str(exc)) from exc
    if isinstance(intake.get("underlying_requests"), list):
        payload["underlying_requests"] = intake["underlying_requests"]
    if intake.get('manual_visit_id'):
        payload.update({key: intake[key] for key in MANUAL_VISIT_FIELDS if key in intake})
        payload['source_sha256'] = str(intake.get('source_sha256') or '')
        payload['personal_profile_id'] = str(intake.get('personal_profile_id') or personal_profile_key)
    return payload


def default_output_path(pdf_path: Path) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{pdf_path.stem}.draft.json"


def main(argv: list[str] | None = None) -> int:
    try:
        from scripts.request_exclusions import RequestExclusionError, require_requests_not_excluded
    except ModuleNotFoundError:
        from request_exclusions import RequestExclusionError, require_requests_not_excluded
    parser = argparse.ArgumentParser(description="Build a Gmail draft payload for a generated honorários PDF.")
    parser.add_argument("intake", type=Path, help="Path to intake JSON.")
    parser.add_argument("--pdf", required=True, type=Path, help="Generated PDF to attach.")
    parser.add_argument("--email-config", type=Path, default=DEFAULT_EMAIL_CONFIG, help="Path to email config JSON.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE, help="Generator profile used to resolve an opt-in email signature template.")
    parser.add_argument("--court-emails", type=Path, default=DEFAULT_COURT_EMAILS, help="Path to known court email directory.")
    parser.add_argument("--output", type=Path, help="Output draft payload JSON path.")
    parser.add_argument("--duplicate-index", type=Path, default=ROOT / "data" / "duplicate-index.json",
                        help="History path whose sibling request-exclusion ledger protects this runtime.")
    args = parser.parse_args(argv)

    try:
        intake = load_json(args.intake)
        require_requests_not_excluded(intake, args.duplicate_index)
        email_config = load_json(args.email_config)
        directory = json.loads(resolve_json_path(args.court_emails).read_text(encoding="utf-8"))
        signature_name = ""
        personal_profile_key = ''
        if intake.get('travel_group_id') or (not intake.get("email_body") and (intake.get('claim_interpreting', True) is False or "{{signature_name}}" in str(email_config.get("body") or ""))):
            profile = load_json(args.profile)
            signature_name = str(profile.get("signature_name") or profile.get("applicant_name") or "")
            personal_profile_key = profile_binding(profile)
        payload = build_email_payload(intake, args.pdf, email_config, directory, signature_name=signature_name, personal_profile_key=personal_profile_key)
        output_path = args.output or default_output_path(args.pdf)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (IntakeError, RequestExclusionError, OSError, json.JSONDecodeError) as exc:
        print(f"Cannot build Gmail draft payload: {exc}", file=sys.stderr)
        return 2

    print(f"Draft payload: {output_path}")
    print(f"To: {payload['to']}")
    print(f"Subject: {payload['subject']}")
    print("Gmail action: _create_draft only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
