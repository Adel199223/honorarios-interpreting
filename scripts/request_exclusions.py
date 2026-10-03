"""Read-only guards for explicit local request exclusions, separate from Sent.

Only ``excluded_cases`` creates these blockers. Police forms, PAC descriptions,
source hashes and arbitrary completion text never manufacture a case/date or
email-submission record. Callers resolve the effective service date through the
ordinary domain helper before asking for an individual match.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

try:
    from scripts.request_identity import normalize_case_number, normalize_period_label, request_identity_key, request_identity_keys_overlap
except ModuleNotFoundError:
    from request_identity import normalize_case_number, normalize_period_label, request_identity_key, request_identity_keys_overlap


MAX_LEDGER_BYTES = 5 * 1024 * 1024
MAX_EXCLUDED_REQUESTS = 10000
_CASE = re.compile(r'\d+/\d{2}\.\d[A-Z][A-Z0-9]*(?:\.[A-Z0-9]+)*')
_HASH = re.compile(r'[a-fA-F0-9]{64}')
_INVALID_LEDGER = 'Saved request exclusions could not be checked. Repair the local exclusion records before preparing or recording another request.'
_INVALID_IDENTITY = 'Every request needs a valid case number, service date and service period before its exclusions can be checked.'


class RequestExclusionError(ValueError):
    """An explicit exclusion or unreadable exclusion state prevents new work."""


def exclusion_ledger_path(duplicate_index_path: str | Path) -> Path:
    """Stay beside the caller's history, including an isolated test runtime."""
    return Path(duplicate_index_path).with_name('paper-submissions.local.json')


def _short_text(value: Any, maximum: int, *, required: bool = False) -> str:
    if value is None and not required:
        return ''
    if not isinstance(value, str) or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise RequestExclusionError(_INVALID_LEDGER)
    result = value.strip()
    if required and not result:
        raise RequestExclusionError(_INVALID_LEDGER)
    return result


def _identity(record: dict[str, Any]) -> tuple[str, str, str]:
    case_number = normalize_case_number(_short_text(record.get('case_number'), 128, required=True))
    service_date = _short_text(record.get('service_date'), 10, required=True)
    period = _short_text(record.get('service_period_label'), 200)
    if not _CASE.fullmatch(case_number) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', service_date):
        raise RequestExclusionError(_INVALID_LEDGER)
    try:
        date.fromisoformat(service_date)
    except ValueError:
        raise RequestExclusionError(_INVALID_LEDGER) from None
    return case_number, service_date, period


def _source_filename(value: Any) -> str:
    filename = _short_text(value, 255)
    if filename in {'.', '..'} or any(char in filename for char in '/\\:'):
        raise RequestExclusionError(_INVALID_LEDGER)
    return filename


def validate_request_exclusion_payload(payload: Any) -> list[dict[str, Any]]:
    """Validate a present ledger and return independent, display-safe blockers.

    Extra original evidence remains in the ledger/backup. It is intentionally
    absent from these results: a local path, free-form reason, Gmail identifier,
    submission date or claimed Sent status must not leak into the warning or
    change the meaning of an explicit exclusion. Older forms-only ledgers are
    valid and have no case exclusions.
    """
    if not isinstance(payload, dict) or type(payload.get('schema_version')) is not int or payload['schema_version'] != 1:
        raise RequestExclusionError(_INVALID_LEDGER)
    # Restores retain all original evidence. Check the complete durable form,
    # not just normalized blockers, so a valid backup cannot become unreadable
    # immediately after the normal atomic JSON writer adds indentation. Bound
    # CRLF too: Windows text writes add those bytes, and backups are portable.
    try:
        durable_bytes = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').replace('\n', '\r\n').encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise RequestExclusionError(_INVALID_LEDGER) from None
    if len(durable_bytes) > MAX_LEDGER_BYTES:
        raise RequestExclusionError(_INVALID_LEDGER)
    for name in ('forms', 'standing_exclusions'):
        if name in payload and (not isinstance(payload[name], list) or len(payload[name]) > MAX_EXCLUDED_REQUESTS
                                or any(not isinstance(row, dict) for row in payload[name])):
            raise RequestExclusionError(_INVALID_LEDGER)
    rows = payload.get('excluded_cases', [])
    if not isinstance(rows, list) or len(rows) > MAX_EXCLUDED_REQUESTS:
        raise RequestExclusionError(_INVALID_LEDGER)
    exclusions = []
    for row in rows:
        if not isinstance(row, dict):
            raise RequestExclusionError(_INVALID_LEDGER)
        case_number, service_date, period = _identity(row)
        # An ambiguous alias could otherwise widen a period-specific exclusion.
        period_alias = _short_text(row.get('service_period'), 200)
        if period_alias and (not period or normalize_period_label(period_alias) != normalize_period_label(period)):
            raise RequestExclusionError(_INVALID_LEDGER)
        completion = _short_text(row.get('completion_evidence'), 2000)
        _short_text(row.get('reason'), 4000)
        kind = 'user_confirmed_done' if completion == 'user_confirmed_done' else 'user_excluded'
        result = {'kind': kind, 'case_number': case_number, 'service_date': service_date,
                  'service_period_label': period,
                  'reason': ('You confirmed this request was already handled.' if kind == 'user_confirmed_done'
                             else 'You asked to exclude this request from fee preparation.')}
        source_hash = _short_text(row.get('source_sha256'), 64)
        if source_hash:
            if not _HASH.fullmatch(source_hash):
                raise RequestExclusionError(_INVALID_LEDGER)
            result['source_sha256'] = source_hash.lower()
        filename = _source_filename(row.get('source_filename'))
        if filename:
            result['source_filename'] = filename
        if 'source_filenames' in row:
            filenames = row['source_filenames']
            if not isinstance(filenames, list) or len(filenames) > 100:
                raise RequestExclusionError(_INVALID_LEDGER)
            names = [_source_filename(value) for value in filenames]
            if any(not name for name in names):
                raise RequestExclusionError(_INVALID_LEDGER)
            result['source_filenames'] = names
        exclusions.append(result)
    return exclusions


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RequestExclusionError(_INVALID_LEDGER)
        result[key] = value
    return result


def load_request_exclusions(ledger_path: str | Path) -> list[dict[str, Any]]:
    """Reload bounded local evidence on each guard; never write or cache it."""
    try:
        with Path(ledger_path).open('rb') as source:
            raw = source.read(MAX_LEDGER_BYTES + 1)
    except FileNotFoundError:
        return []
    except OSError:
        raise RequestExclusionError(_INVALID_LEDGER) from None
    if len(raw) > MAX_LEDGER_BYTES:
        raise RequestExclusionError(_INVALID_LEDGER)
    try:
        payload = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_json_object)
        return validate_request_exclusion_payload(payload)
    except (UnicodeError, ValueError, RecursionError):
        raise RequestExclusionError(_INVALID_LEDGER) from None


def match_request_exclusion(intake: dict[str, Any], exclusions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pure identity/period match against validated rows; source is corroboration.

    An incomplete review identity has no match yet. A shared photo hash never
    excludes other cases, days or explicitly distinct same-day periods.
    """
    try:
        _identity(intake)
    except (RequestExclusionError, AttributeError):
        return None
    key = request_identity_key(intake)
    matches = [row for row in exclusions if request_identity_keys_overlap(key, request_identity_key(row))]
    if not matches:
        return None
    # A later explicit completion retains that stronger user evidence; all
    # matching exclusions still block. No submission mechanism is inferred.
    row = next((item for item in matches if item['kind'] == 'user_confirmed_done'), matches[0])
    result = {**row}
    if 'source_filenames' in row:
        result['source_filenames'] = list(row['source_filenames'])
    source_hash = str(intake.get('source_sha256') or '').strip().lower()
    result['matching_source_sha256'] = bool(row.get('source_sha256') and source_hash == row['source_sha256'])
    return result


def find_request_exclusion(intake: dict[str, Any], duplicate_index_path: str | Path) -> dict[str, Any] | None:
    """Check the current runtime's ledger, even while identity is incomplete."""
    return match_request_exclusion(intake, load_request_exclusions(exclusion_ledger_path(duplicate_index_path)))


def format_request_exclusion(exclusion: dict[str, Any]) -> str:
    title = 'Already handled — confirmed by you.' if exclusion['kind'] == 'user_confirmed_done' else 'Excluded at your request.'
    period = str(exclusion.get('service_period_label') or '')
    identity = f"{exclusion['case_number']} on {exclusion['service_date']}" + (f' ({period})' if period else '')
    return f'{title} {identity}. No new fee request or draft should be created for this service.'


def require_not_excluded(intake: dict[str, Any], duplicate_index_path: str | Path) -> None:
    exclusion = find_request_exclusion(intake, duplicate_index_path)
    if exclusion:
        raise RequestExclusionError(format_request_exclusion(exclusion))


def require_requests_not_excluded(payload: dict[str, Any], duplicate_index_path: str | Path) -> None:
    """Final guard for every single/grouped child before local/provider writes.

    Unlike incomplete review matching, writing boundaries require valid
    identities. Resolve dates with the existing domain helper; this module does
    not establish separate photo-date or user-confirmation rules.
    """
    exclusions = load_request_exclusions(exclusion_ledger_path(duplicate_index_path))
    if not isinstance(payload, dict):
        raise RequestExclusionError(_INVALID_IDENTITY)
    children = payload.get('underlying_requests')
    if children is not None and (not isinstance(children, list) or not children
                                 or len(children) > MAX_EXCLUDED_REQUESTS
                                 or any(not isinstance(row, dict) or row.get('underlying_requests') for row in children)):
        raise RequestExclusionError(_INVALID_IDENTITY)
    requests = list(children or [])
    if not children or any(payload.get(key) for key in ('case_number', 'service_date', 'photo_metadata_date')):
        requests.append(payload)
    try:
        from scripts.generate_pdf import get_service_date_value
    except ModuleNotFoundError:
        from generate_pdf import get_service_date_value
    for request in requests:
        try:
            resolved = {**request, 'service_date': get_service_date_value(request)}
            _identity(resolved)
        except (TypeError, ValueError):
            raise RequestExclusionError(_INVALID_IDENTITY) from None
        exclusion = match_request_exclusion(resolved, exclusions)
        if exclusion:
            raise RequestExclusionError(format_request_exclusion(exclusion))
