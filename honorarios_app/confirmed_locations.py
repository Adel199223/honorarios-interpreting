"""Pure, bounded reuse of location answers for the same reviewed source.

The catalog contains confirmed facts, not source text, request snapshots or
permission to prepare/send anything. Every normal domain guard still applies.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date
from typing import Any

from scripts.entity_rules import build_service_place_clause, classify_entity_type, normalize_text, source_mentions_pj_context
from scripts.request_identity import normalize_case_number
from scripts.source_parsing import explicit_service_places
from .photo_defaults import apply_capture_city_answer
from .source_cases import valid_source_case

MAX_CONFIRMATIONS = 128
MAX_SERVICE_DATES = 16
PROOF_KEY = 'confirmed_source_location_evidence'
HOST_FIELDS = {'service_place', 'service_entity', 'service_entity_type', 'entities_differ', 'service_place_phrase'}
ROUTE_FIELDS = {'payment_entity', 'addressee', 'recipient_email', 'court_email', 'court_email_key',
                'recipient_override_reason', 'court_email_override_reason'}
TRAVEL_FIELDS = {'transport.destination', 'transport.km_one_way'}
CITY_FIELDS = {'photo_capture_city', 'photo_capture_city_source_sha256'}
DERIVED_FIELDS = HOST_FIELDS | ROUTE_FIELDS | TRAVEL_FIELDS | CITY_FIELDS
METADATA_FIELDS = {'photo_defaults_applied', 'photo_capture_city_applied_fields', 'source_location_evidence'}
KINDS = {'court', 'ministerio_publico', 'gnr', 'psp', 'police', 'other'}


def _text(value: Any, maximum: int = 200, *, multiline: bool = False) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
            and not any(ord(char) < 32 and not (multiline and char == '\n') for char in value))


def _iso(value: Any) -> bool:
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return ' '.join(normalize_text(left).split()) == ' '.join(normalize_text(right).split())
    return type(left) is type(right) and left == right


def _get(value: dict[str, Any], field: str) -> Any:
    if field.startswith('transport.'):
        transport = value.get('transport')
        return transport.get(field.split('.', 1)[1]) if isinstance(transport, dict) else None
    return value.get(field)


def _set(value: dict[str, Any], field: str, item: Any) -> None:
    if field.startswith('transport.'):
        value.setdefault('transport', {})[field.split('.', 1)[1]] = copy.deepcopy(item)
    else:
        value[field] = copy.deepcopy(item)


def _remove(value: dict[str, Any], field: str) -> None:
    if field.startswith('transport.'):
        transport = value.get('transport')
        if isinstance(transport, dict):
            transport.pop(field.split('.', 1)[1], None)
    else:
        value.pop(field, None)


def _binding(intake: dict[str, Any]) -> dict[str, str]:
    return {'source_kind': str(intake.get('source_kind') or ''),
            'source_sha256': str(intake.get('source_sha256') or ''),
            'case_number': normalize_case_number(intake.get('case_number') or ''),
            'service_date': str(intake.get('service_date') or ''),
            'source_text_sha256': hashlib.sha256(str(intake.get('source_text') or '').encode('utf-8')).hexdigest()}


def _entry_fingerprint(entry: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def _metadata_diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    missing = object()
    changes = []

    def visit(path: list[str], prior: Any, current: Any) -> None:
        if isinstance(current, dict) and (prior is missing or isinstance(prior, dict)):
            for key in sorted(set(current) | (set(prior) if isinstance(prior, dict) else set())):
                visit([*path, key], prior.get(key, missing) if isinstance(prior, dict) else missing, current.get(key, missing))
        elif prior != current:
            changes.append({'path': path, 'before_present': prior is not missing,
                            'before': None if prior is missing else copy.deepcopy(prior),
                            'after_present': current is not missing,
                            'after': None if current is missing else copy.deepcopy(current)})

    for field in sorted(METADATA_FIELDS):
        visit([field], before.get(field, missing), after.get(field, missing))
    return changes


def _revoke_metadata(candidate: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    for change in reversed(changes):
        if not isinstance(change, dict):
            continue
        path = change.get('path')
        if (not isinstance(path, list) or not 1 <= len(path) <= 8 or path[0] not in METADATA_FIELDS
                or not all(isinstance(key, str) for key in path)):
            continue
        parent, stack = candidate, []
        for key in path[:-1]:
            if not isinstance(parent.get(key), dict):
                break
            stack.append((parent, key))
            parent = parent[key]
        else:
            key = path[-1]
            if ((key in parent) != bool(change.get('after_present'))
                    or (key in parent and parent[key] != change.get('after'))):
                continue
            if change.get('before_present'):
                parent[key] = copy.deepcopy(change.get('before'))
            else:
                parent.pop(key, None)
                for owner, name in reversed(stack):
                    if owner[name]:
                        break
                    owner.pop(name)


def _catalog(preferences: dict[str, Any]) -> list[dict[str, Any]]:
    records = preferences.get('confirmed_source_locations', [])
    if not isinstance(records, list) or len(records) > MAX_CONFIRMATIONS:
        raise ValueError('Confirmed source locations must be a bounded list.')
    required = {'id', 'source_sha256', 'case_number', 'allowed_service_dates', 'confirmation_date', 'evidence_reference'}
    optional = {'capture_city', 'host', 'payment_route', 'travel'}
    result, seen_ids, seen_keys = [], set(), set()
    for raw in records:
        if (not isinstance(raw, dict) or not required <= raw.keys() or raw.keys() - required - optional
                or not isinstance(raw['id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', raw['id'])
                or raw['id'] in seen_ids or not isinstance(raw['source_sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', raw['source_sha256'])
                or not valid_source_case(raw['case_number']) or not _iso(raw['confirmation_date'])
                or not _text(raw['evidence_reference'], 500)):
            raise ValueError('A confirmed source location has invalid identity or provenance.')
        dates = raw['allowed_service_dates']
        if (not isinstance(dates, list) or not 1 <= len(dates) <= MAX_SERVICE_DATES
                or not all(_iso(item) for item in dates) or len(set(dates)) != len(dates)):
            raise ValueError('Every confirmation needs distinct valid allowed service dates.')
        case = normalize_case_number(raw['case_number'])
        keys = {(raw['source_sha256'], case, day) for day in dates}
        if seen_keys.intersection(keys):
            raise ValueError('Confirmed source locations overlap for the same source, case and date.')
        if not optional.intersection(raw):
            raise ValueError('A confirmation must contain a location fact group.')
        if 'capture_city' in raw and not _text(raw['capture_city'], 120):
            raise ValueError('The confirmed capture city is invalid.')
        host = raw.get('host')
        if 'host' in raw and (not isinstance(host, dict) or set(host) != {
                'service_place', 'service_entity', 'service_entity_type', 'entities_differ'}
                or not all(_text(host.get(key), 300) for key in ('service_place', 'service_entity'))
                or host.get('service_entity_type') not in KINDS or type(host.get('entities_differ')) is not bool
                or classify_entity_type(host['service_entity']) != host['service_entity_type']):
            raise ValueError('The confirmed host must keep source agency and physical host separate.')
        route = raw.get('payment_route')
        if 'payment_route' in raw and (not isinstance(route, dict) or set(route) != {'payment_entity', 'addressee', 'recipient_email'}
                or not _text(route.get('payment_entity'), 300) or not _text(route.get('addressee'), 600, multiline=True)
                or not isinstance(route.get('recipient_email'), str)
                or not re.fullmatch(r'[A-Za-z0-9._%+\-]+@tribunais\.org\.pt', route['recipient_email'], re.IGNORECASE)):
            raise ValueError('The confirmed payment route is invalid; ordinary recipient validation still applies.')
        travel = raw.get('travel')
        if 'travel' in raw and (not isinstance(travel, dict) or set(travel) != {'personal_profile_id', 'origin', 'destination', 'km_one_way'}
                or not _text(travel.get('personal_profile_id'), 120) or not _text(travel.get('origin'), 300) or not _text(travel.get('destination'), 300)
                or type(travel.get('km_one_way')) is not int or not 0 <= travel['km_one_way'] <= 5000):
            raise ValueError('The confirmed travel must be bound to one personal profile and destination.')
        result.append(copy.deepcopy(raw) | {'case_number': case})
        seen_ids.add(raw['id'])
        seen_keys.update(keys)
    return result


def apply_confirmed_source_location(intake: dict[str, Any], *, preferences: dict[str, Any],
                                    directory: list[dict[str, Any]], personal_profile_id: str = '',
                                    personal_profile_origin: str = '',
                                    automatic_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a new intake and a decision; never write or choose a service date.

    ``automatic_fields`` comes from current server-selected profile defaults,
    not a caller's assertion. Nonempty untracked values and deliberate clears
    remain authoritative. A source conflict must be a blocking review result.
    """
    candidate = copy.deepcopy(intake)
    applied: dict[str, Any] = {}

    def result(status: str, conflicts: list[str] | None = None, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        return {'status': status, 'intake': candidate, 'applied_fields': copy.deepcopy(applied),
                'conflicts': conflicts or [], 'evidence': evidence or {}}

    try:
        catalog = _catalog(preferences)
    except (ValueError, TypeError, AttributeError) as exc:
        return result('invalid_configuration', [str(exc)])
    binding = _binding(candidate)
    profile = candidate.get('auto_profile') or {}
    explicit_profile = isinstance(profile, dict) and profile.get('mode') == 'explicit_profile'
    selected_profile = personal_profile_id or str(candidate.get('personal_profile_id') or '')
    transport = candidate.get('transport')
    selected_origin = str((transport.get('origin') or '') if isinstance(transport, dict) and 'origin' in transport
                          else personal_profile_origin or '')
    if 'transport.origin' in (candidate.get('review_cleared_fields') or []):
        selected_origin = ''
    previous = candidate.pop(PROOF_KEY, None)
    old_applied = previous.get('applied_fields') if isinstance(previous, dict) else None
    old_applied = old_applied if isinstance(old_applied, dict) else {}
    old_metadata = previous.get('metadata_changes') if isinstance(previous, dict) else None
    old_metadata = old_metadata if isinstance(old_metadata, list) and len(old_metadata) <= 512 else []
    metadata_changes = []
    manual = {}
    if isinstance(previous, dict):
        old_manual = previous.get('manual_overrides')
        for field in (old_manual if isinstance(old_manual, dict) else {}):
            if field in DERIVED_FIELDS:
                manual[field] = copy.deepcopy(_get(candidate, field))
        for field, value in (old_applied or {}).items():
            if field in DERIVED_FIELDS and _get(candidate, field) != value:
                manual[field] = copy.deepcopy(_get(candidate, field))
    # Old evidence can revoke only its unchanged derived values, never grant
    # authority to a new identity or erase a later manual value.
    previous_entry = next((entry for entry in catalog if isinstance(previous, dict)
                           and entry['id'] == previous.get('confirmation_id')), None)
    stale = isinstance(previous, dict) and (explicit_profile or any(previous.get(key) != value for key, value in binding.items())
            or previous_entry is None or previous.get('confirmation_fingerprint') != _entry_fingerprint(previous_entry))
    if stale and isinstance(old_applied, dict):
        for field, value in old_applied.items():
            if field in DERIVED_FIELDS and _get(candidate, field) == value:
                _remove(candidate, field)
        _revoke_metadata(candidate, old_metadata)
    stale_travel = bool(isinstance(previous, dict) and previous.get('travel_personal_profile_id')
                        and (previous['travel_personal_profile_id'] != selected_profile
                             or not _same(previous.get('travel_origin'), selected_origin)
                             or not _same(previous.get('travel_destination'), _get(candidate, 'transport.destination'))))
    if stale_travel and isinstance(old_applied, dict):
        for field in ('transport.km_one_way',):
            if field in old_applied and _get(candidate, field) == old_applied[field]:
                _remove(candidate, field)
        candidate['source_transport_distance_pending'] = True
    if (isinstance(previous, dict) and previous.get('travel_destination')
            and all(previous.get(key) == binding[key] for key in ('source_kind', 'source_sha256', 'case_number', 'service_date'))
            and not _same(previous['travel_destination'], _get(candidate, 'transport.destination'))):
        manual['transport.destination'] = copy.deepcopy(_get(candidate, 'transport.destination'))
    if not catalog:
        return result('disabled')
    if (candidate.get('source_kind') != 'photo' or not re.fullmatch(r'[a-f0-9]{64}', binding['source_sha256'])
            or not valid_source_case(binding['case_number']) or not _iso(binding['service_date'])):
        return result('no_match')
    matches = [entry for entry in catalog if entry['source_sha256'] == binding['source_sha256']
               and entry['case_number'] == binding['case_number'] and binding['service_date'] in entry['allowed_service_dates']]
    if not matches:
        return result('no_match')
    entry = matches[0]
    if (explicit_profile
            or 'source_text' in (candidate.get('review_cleared_fields') or [])
            or not str(candidate.get('source_text') or '').strip()):
        return result('explicit_override')
    cleared = set(candidate.get('review_cleared_fields') or [])
    protected = cleared | set(manual)
    automatic = dict(automatic_fields or {})
    defaults = candidate.get('photo_defaults_applied') or {}
    if isinstance(defaults, dict):
        automatic.update({key: defaults[key] for key in ('payment_entity', 'recipient_email', 'addressee', 'service_place') if key in defaults})
    venue_proof = candidate.get('source_location_evidence') or {}
    if (isinstance(venue_proof, dict) and venue_proof.get('source_sha256') == binding['source_sha256']
            and venue_proof.get('source_text_sha256') == binding['source_text_sha256']
            and venue_proof.get('source') in {'verified_gps_source_venue', 'gnr_capture_city_default'}):
        venue_applied = venue_proof.get('applied_fields')
        if isinstance(venue_applied, dict):
            automatic.update(venue_applied)
        for key in ('service_place', 'service_entity', 'service_entity_type'):
            if key in venue_proof:
                automatic[key] = venue_proof[key]
    if not stale and isinstance(old_applied, dict):
        automatic.update(old_applied)

    def editable(field: str, value: Any) -> bool:
        current = _get(candidate, field)
        if field == 'transport.km_one_way' and current == 0 and value != 0:
            return False
        return field not in protected and (current in (None, '') or _same(current, value)
                                        or (field in automatic and current == automatic[field]))

    def supply(field: str, value: Any) -> None:
        if editable(field, value) and _get(candidate, field) != value:
            _set(candidate, field, value)
            applied[field] = copy.deepcopy(value)

    conflicts: list[str] = []
    host = entry.get('host')
    host_active = isinstance(host, dict) and not protected.intersection(HOST_FIELDS)
    if host_active and not editable('service_place', host['service_place']):
        host_active = False  # A deliberate current host overrides remembered facts.
    manual_host = bool(isinstance(host, dict) and not host_active
                       and ('service_place' in protected or not editable('service_place', host['service_place'])))
    if manual_host:
        protected.update(TRAVEL_FIELDS)
        # Reconcile only dependencies this memory actually supplied. Source
        # agency and deliberate user edits are not the physical host.
        for field in ('service_place_phrase', *TRAVEL_FIELDS):
            if field in old_applied and _get(candidate, field) == old_applied[field]:
                _remove(candidate, field)
        if old_applied and candidate.get('service_place'):
            candidate['service_place_phrase'] = build_service_place_clause(
                {'service_place': candidate['service_place'], 'source_text': candidate.get('source_text', '')},
                str(candidate.get('service_entity') or ''))
            candidate['source_transport_distance_pending'] = True
    if isinstance(host, dict) and not protected.intersection(HOST_FIELDS):
        text = str(candidate.get('source_text') or '')
        named_places = explicit_service_places(text)
        if named_places and any(not _same(place, host['service_place']) for place in named_places):
            conflicts.append('The current source names a different physical host than its saved confirmation.')
        expected_kind = host['service_entity_type']
        current_kind = candidate.get('service_entity_type')
        label_kind = classify_entity_type(str(candidate.get('service_entity') or ''))
        if (current_kind and current_kind != expected_kind and not editable('service_entity_type', expected_kind)):
            conflicts.append('The current recovered service agency type differs from the saved source agency.')
        if (candidate.get('service_entity') and label_kind not in {'other', expected_kind}
                and not editable('service_entity', host['service_entity'])):
            conflicts.append('The current recovered service agency label differs from the saved source agency.')
        phrase = str(candidate.get('service_place_phrase') or '')
        expected_phrase = build_service_place_clause({'service_place': host['service_place'], 'source_text': text},
                                                     str(candidate.get('service_entity') or host['service_entity']))
        if (phrase and normalize_text(host['service_place']) not in normalize_text(phrase)
                and not editable('service_place_phrase', expected_phrase)):
            conflicts.append('The current service-location wording names an unresolved different host.')
        if source_mentions_pj_context({'source_text': text}) and expected_kind != 'police':
            conflicts.append('The current source names Polícia Judiciária; the saved source agency differs.')
        own_header = '\n'.join(text.splitlines()[:24])[:1800]
        for line in own_header.splitlines():
            if re.match(r'^\s*(?:guarda nacional republicana|gnr\b|policia de seguranca publica|psp\b|policia judiciaria|ministerio publico|procuradoria)', normalize_text(line)):
                kind = classify_entity_type(line)
                if kind != expected_kind and not (expected_kind == 'police' and kind == 'gnr' and source_mentions_pj_context({'source_text': text})):
                    conflicts.append('The current source agency conflicts with the saved confirmation.')
                    break
    city = entry.get('capture_city')
    if city and isinstance(defaults, dict) and defaults.get('photo_city_source') == 'verified_gps_area':
        if defaults.get('photo_city') and not _same(defaults['photo_city'], city):
            conflicts.append('Current original-GPS city evidence conflicts with the saved capture-city answer.')
    if conflicts:
        return result('source_conflict', conflicts)

    independent_city = bool(city and isinstance(defaults, dict) and _same(defaults.get('photo_city'), city)
                            and (defaults.get('photo_city_source') == 'verified_gps_area'
                                 or (candidate.get('photo_capture_city_source_sha256') == binding['source_sha256']
                                     and _same(candidate.get('photo_capture_city'), city))))
    if city and not independent_city and preferences.get('photo_city_court') is True and not protected.intersection(CITY_FIELDS) and editable('photo_capture_city', city):
        before = copy.deepcopy(candidate)
        original_clears = copy.deepcopy(candidate.get('review_cleared_fields'))
        if protected:
            candidate['review_cleared_fields'] = sorted(protected)
        apply_capture_city_answer(candidate, city, preferences=preferences, directory=directory)
        if original_clears is None:
            candidate.pop('review_cleared_fields', None)
        else:
            candidate['review_cleared_fields'] = original_clears
        metadata_changes = _metadata_diff(before, candidate)
        for field in DERIVED_FIELDS:
            if _get(before, field) != _get(candidate, field) and _get(candidate, field) is not None:
                applied[field] = copy.deepcopy(_get(candidate, field))
        current_defaults = candidate.get('photo_defaults_applied') or {}
        if isinstance(current_defaults, dict):
            automatic.update({key: current_defaults[key] for key in ('payment_entity', 'recipient_email', 'addressee', 'service_place') if key in current_defaults})
    if host_active:
        for field, value in host.items():
            supply(field, value)
        if editable('service_place_phrase', ''):
            phrase = build_service_place_clause({'service_place': candidate.get('service_place', ''),
                                                'source_text': candidate.get('source_text', '')},
                                               str(candidate.get('service_entity') or ''))
            supply('service_place_phrase', phrase)
    route = entry.get('payment_route')
    if isinstance(route, dict) and not protected.intersection(ROUTE_FIELDS) and all(editable(field, value) for field, value in route.items()):
        for field, value in route.items():
            supply(field, value)
        for field in ('court_email', 'court_email_key', 'recipient_override_reason', 'court_email_override_reason'):
            if candidate.get(field) and field in automatic:
                candidate[field] = ''
                applied[field] = ''
    travel = entry.get('travel')
    travel_matches = (isinstance(travel, dict) and travel['personal_profile_id'] == selected_profile
                      and bool(selected_origin) and _same(travel['origin'], selected_origin))
    if travel_matches and not protected.intersection(TRAVEL_FIELDS | {'transport.origin'}):
        values = {'transport.destination': travel['destination'], 'transport.km_one_way': travel['km_one_way']}
        if all(editable(field, value) for field, value in values.items()):
            for field, value in values.items():
                supply(field, value)
    retained = {field: value for field, value in (old_applied or {}).items()
                if not stale and not (stale_travel and field == 'transport.km_one_way')
                and field in DERIVED_FIELDS and _get(candidate, field) == value}
    proof = {**binding, 'source': 'previously_confirmed_source_location', 'confirmation_id': entry['id'],
             'confirmation_fingerprint': _entry_fingerprint(entry),
             'confirmation_date': entry['confirmation_date'], 'evidence_reference': entry['evidence_reference'],
             'applied_fields': {**retained, **copy.deepcopy(applied)},
             'manual_overrides': manual,
             'metadata_changes': ([] if stale else copy.deepcopy(old_metadata)) + metadata_changes,
             'reason': 'Previously confirmed for this source. The physical host is the saved answer; source agency remains separate. These are editable saved answers, not printed evidence, embedded GPS or proof of attendance.'}
    facts = {}
    if city and _same(candidate.get('photo_capture_city'), city):
        proof['capture_city'] = city
        facts['capture_city'] = city
    if isinstance(host, dict) and _same(candidate.get('service_place'), host['service_place']):
        facts['physical_host'] = host['service_place']
        proof['source_agency_context'] = {field: candidate.get(field) for field in ('service_entity', 'service_entity_type')}
    if isinstance(route, dict) and all(_same(candidate.get(field), value) for field, value in route.items()):
        facts['payment_route'] = copy.deepcopy(route)
    if not stale and not stale_travel and isinstance(previous, dict) and previous.get('travel_personal_profile_id'):
        for field in ('travel_personal_profile_id', 'travel_origin', 'travel_destination', 'travel_context_source'):
            if field in previous:
                proof[field] = copy.deepcopy(previous[field])
    if travel_matches:
        proof['travel_personal_profile_id'] = selected_profile
        proof['travel_origin'] = selected_origin
        proof['travel_destination'] = travel['destination']
        if _same(_get(candidate, 'transport.destination'), travel['destination']) and _get(candidate, 'transport.km_one_way') == travel['km_one_way']:
            facts['travel'] = copy.deepcopy(travel)
    proof['fact_groups'] = facts
    candidate[PROOF_KEY] = proof
    return result('applied' if applied else 'matched', evidence=proof)
