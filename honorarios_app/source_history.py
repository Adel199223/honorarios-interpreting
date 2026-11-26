"""Conservative history identity from a foreground completed fee demand.

This evidence can stop a repeated request. It never supplies generation fields,
establishes work scope, or proves that the photographed form was submitted.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any
from pathlib import Path

from scripts.entity_rules import normalize_text
from scripts.source_parsing import PORTUGUESE_MONTHS
from .source_cases import (source_case_rows, source_scope_requires_review,
                           documentary_case_references, documentary_case_role_error)

_DATE = (r'(?:20\d{2}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]20\d{2}|'
         r'\d{1,2}\s+(?:de\s+)?(?:' + '|'.join(PORTUGUESE_MONTHS) + r')\s+de\s+20\d{2})')
_PERFORMED = r'(?:ter\s+)?(?:desempenhado\s+as\s+funcoes|prestado\s+(?:o\s+)?servico|realizado\s+(?:o\s+)?servico)'
_CLAUSE = re.compile(r'\b(?:no\s+dia|na\s+data\s+de|em)\s+(?P<date>' + _DATE +
                     r')\s*,?\s*' + _PERFORMED + r'\b')
_REJECT = re.compile(r'\b(?:nao|nunca|cancelad[oa]|anulad[oa]|adiad[oa]|eventual|talvez|se\s+vier|ira|devera)\b')


def _iso_date(value: str) -> str:
    if re.fullmatch(r'20\d{2}-\d{2}-\d{2}', value):
        return date.fromisoformat(value).isoformat()
    numeric = re.fullmatch(r'(\d{1,2})[/-](\d{1,2})[/-](20\d{2})', value)
    if numeric:
        day, month, year = map(int, numeric.groups())
    else:
        named = re.fullmatch(r'(\d{1,2})\s+(?:de\s+)?(\w+)\s+de\s+(20\d{2})', value)
        if not named:
            return ''
        day, month_name, year = named.groups()
        day, month, year = int(day), PORTUGUESE_MONTHS[month_name], int(year)
    return date(year, month, day).isoformat()


def completed_fee_source_identity(intake: dict[str, Any]) -> dict[str, str] | None:
    """Recompute from current foreground text, ignoring caller-derived identities.

    OCR visible text is evidence; model fields, notes, filenames and incidental
    background are never searched. A source hash and supported source kind
    keep manual/profile text out of this special path.
    """
    if not isinstance(intake, dict):
        return None
    digest = str(intake.get('source_sha256') or '')
    if (intake.get('source_kind') not in {'photo', 'notification_pdf'}
            or re.fullmatch(r'[0-9a-f]{64}', digest) is None):
        return None
    raw = str(intake.get('source_text') or '')
    if not raw.strip() or len(raw) > 100_000:
        return None
    ai = intake.get('ai_recovery') if isinstance(intake.get('ai_recovery'), dict) else {}
    if source_scope_requires_review(raw, ai):
        return None
    text = normalize_text(raw)
    # Only an exact NUIPC label may touch the digits. Other prefixes retain the
    # existing administrative-reference and suffix-fragmentation safeguards.
    visible = re.sub(r'\bNUIPC(?=\d+\s*/)', 'NUIPC ', raw, flags=re.IGNORECASE)
    rows = source_case_rows(visible, {})
    cases = {row['case_number'] for row in rows if row['case_number']}
    if len(cases) != 1 or any(not row['case_number'] for row in rows):
        return None
    if (not re.search(r'\brequerimento\b', text[:400])
            or not re.search(r'\bvem\s+requerer\b.{0,220}\b(?:pagamento|honorarios)\b', text, re.DOTALL)
            or not re.search(r'\bhonorarios\b', text)):
        return None
    clauses = list(_CLAUSE.finditer(text))
    values = set()
    for clause in clauses:
        left = max(text.rfind(char, 0, clause.start()) for char in '\n;.!?') + 1
        context = text[max(left, clause.start() - 100):clause.end()]
        if _REJECT.search(context):
            return None
        try:
            values.add(_iso_date(clause.group('date')))
        except (ValueError, KeyError):
            return None
    if len(values) != 1 or not clauses:
        return None
    return {'case_number': next(iter(cases)), 'service_date': next(iter(values)),
            'service_period_label': '', 'source_sha256': digest,
            'source_text_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'provenance': 'foreground_completed_fee_demand',
            'label': 'Source service identity — history check only'}


def source_history_exception_fingerprint(intake: dict[str, Any], identity: dict[str, str]) -> str:
    """Bind an explicit separate-service answer to both source and current ID."""
    material = {'source': identity, 'case_number': str(intake.get('case_number') or '').strip(),
                'service_date': str(intake.get('service_date') or '').strip(),
                'service_period_label': str(intake.get('service_period_label') or '').strip()}
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def completed_fee_history_match(intake: dict[str, Any], duplicate_index: str | Path,
                                draft_log: str | Path | list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Shared app/CLI positive-only lookup, using existing period overlap rules."""
    from scripts.generate_pdf import find_duplicate_record, format_duplicate_message
    from scripts.prepare_honorarios import active_drafts_for, load_draft_log
    from scripts.request_exclusions import find_request_exclusion, format_request_exclusion
    from .source_cases import valid_source_case
    identity = completed_fee_source_identity(intake)
    if identity is None:
        return None
    # The photographed claim has no bound period. Keep that uncertainty broad;
    # a changed requested period requires an explicit separate-service answer.
    lookup = identity
    exclusion = find_request_exclusion(lookup, duplicate_index)
    duplicate = find_duplicate_record(lookup, Path(duplicate_index))
    drafts = draft_log if isinstance(draft_log, list) else load_draft_log(Path(draft_log or Path(duplicate_index).with_name('gmail-draft-log.json')))
    active = active_drafts_for(lookup, drafts)
    if not (exclusion or duplicate or active):
        return None
    case = valid_source_case(intake.get('case_number'))
    explicit_date = str(intake.get('service_date_source') or '') in {
        'user_confirmed', 'user_confirmed_exception', 'document_text_user_confirmed', 'photo_metadata_user_confirmed', 'manual', 'user'}
    from scripts.request_identity import normalize_period_label
    period = normalize_period_label(str(intake.get('service_period_label') or ''))
    record = exclusion or duplicate or active[0]
    historical_period = normalize_period_label(str(record.get('service_period_label') or ''))
    conflict = bool((case and case != identity['case_number'])
                    or (explicit_date and str(intake.get('service_date') or '') not in {'', identity['service_date']})
                    or (period and period != historical_period))
    confirmed = bool(conflict and intake.get('service_date_source') == 'user_confirmed_exception'
                     and intake.get('source_history_exception_fingerprint') == source_history_exception_fingerprint(intake, identity))
    prefix = (f"Source service identity — history check only: {identity['case_number']} "
              f"on {identity['service_date']}. The intake date has not been changed. ")
    detail = (format_request_exclusion(exclusion) if exclusion else format_duplicate_message(duplicate) if duplicate
              else 'An active Gmail draft is already recorded for this source service.')
    if conflict and not confirmed:
        detail = 'The edited request identity conflicts with this completed fee source. Confirm a separate service before preparation.'
    return {'identity': identity, 'exclusion': exclusion, 'duplicate': duplicate, 'active': active,
            'conflict': conflict, 'confirmed': confirmed, 'message': prefix + detail}


def source_history_evidence(intake: dict[str, Any]) -> dict[str, Any] | None:
    """Retain local-only source context in prepared metadata, never Gmail args."""
    if (completed_fee_source_identity(intake) is None
            and not documentary_case_references(str(intake.get('source_text') or ''), intake.get('ai_recovery') or {})):
        return None
    keys = ('source_kind', 'source_sha256', 'source_text', 'service_date_source',
            'source_history_exception_fingerprint')
    result = {key: intake[key] for key in keys if key in intake}
    ai = intake.get('ai_recovery')
    if isinstance(ai, dict):
        result['ai_recovery'] = {key: ai[key] for key in ('source_scope', 'incidental_background_text') if key in ai}
    return result


def require_completed_fee_history_clear(payload: dict[str, Any], duplicate_index: str | Path,
                                        draft_log: str | Path | list[dict[str, Any]] | None = None) -> None:
    from scripts.generate_pdf import IntakeError, get_service_date_value
    from scripts.request_identity import normalize_case_number
    children = payload.get('underlying_requests') or [payload]
    for child in children:
        if not isinstance(child, dict):
            continue  # The ordinary payload validator rejects malformed children.
        evidence = child.get('source_history_evidence')
        intake = {**evidence, **child} if isinstance(evidence, dict) else child
        role_error = documentary_case_role_error(intake)
        if role_error:
            # ValueError also remains caught by directly executed CLI modules,
            # whose __main__.IntakeError can be a different class.
            raise ValueError(role_error)
        match = completed_fee_history_match(intake, duplicate_index, draft_log)
        if match and not match['confirmed']:
            # For the actual same request, existing canonical duplicate,
            # exclusion, correction and exact-ID retry guards already apply.
            # This extra guard protects source identities hidden by a different
            # current/default identity; it never replaces those normal guards.
            try:
                same_request = (not match['conflict']
                    and normalize_case_number(str(intake.get('case_number') or '')) == match['identity']['case_number']
                    and get_service_date_value(intake) == match['identity']['service_date'])
            except (ValueError, TypeError):
                same_request = False
            if same_request:
                continue
            raise IntakeError(match['message'])
