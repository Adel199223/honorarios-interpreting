"""Saved photo policy, kept separate from OCR facts and provider configuration."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from scripts.entity_rules import build_service_place_clause, classify_entity_type, normalize_text, source_mentions_pj_context
from scripts.generate_pdf import IntakeError
from scripts.source_parsing import explicit_service_places, ministerio_publico_venue_evidence

ROUTING_FIELDS = ('payment_entity', 'addressee', 'recipient_email', 'court_email',
                  'court_email_key', 'recipient_override_reason', 'court_email_override_reason')
COURT_EMAIL = re.compile(r'[A-Z0-9._%+\-]+@tribunais\.org\.pt', re.IGNORECASE)
_NONCOURT_VENUE_WARNING = ('The source names a non-court agency but does not establish the physical service venue. '
                          'Confirm the building and city; the court venue default was not applied.')


def load_photo_defaults(ai_config: Path) -> dict[str, Any]:
    path = ai_config.with_name('photo-defaults.local.json')
    if not path.exists():
        return {}
    try:
        preferences = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise IntakeError('The saved photo defaults could not be read. Review the local photo preferences.') from exc
    if not isinstance(preferences, dict):
        raise IntakeError('Saved photo defaults must be a JSON object.')
    return preferences


def _valid_date(value: Any) -> str:
    value = str(value or '').strip()
    try:
        return value if date.fromisoformat(value).isoformat() == value else ''
    except ValueError:
        return ''


def _city_key(value: Any) -> str:
    return ' '.join(normalize_text(str(value or '')).split())


def _corroborated_letterhead_agency(text: str) -> dict[str, str]:
    """Recover a cropped agency label, never an address or physical host."""
    header = '\n'.join(text.splitlines()[:24])[:1800]
    normalized = normalize_text(header)
    body = re.search(r'\b(?:auto|uto)\s+de\b|\b(?:despacho|certidao|notificacao|declaro|declarou|compareceu)\b', normalized)
    if body:
        header, normalized = header[:body.start()], normalized[:body.start()]
    # A quoted contact, court instruction or forwarded message is not the
    # source's own letterhead. Do not search the document body for an email.
    if re.search(r'\b(tribunal|juizo|ministerio publico|procuradoria|notifique|notificar|remeta|remeter|'
                 r'forwarded|encaminhad[ao]|mensagem original|original message)\b|'
                 r'(?:^|\n)\s*(?:(?:de|from|para|to|assunto|subject|fwd|fw)\s*:|>)', normalized):
        return {}
    domains = {match.lower().rstrip('.') for match in re.findall(
        r'[a-z0-9._%+\-]+@([a-z0-9.\-]+)', normalized)}
    kinds = {
        'gnr': ('Guarda Nacional Republicana', r'\bnacional republicana\b', 'gnr.pt'),
        'psp': ('Polícia de Segurança Pública', r'\bseguranca publica\b', 'psp.pt'),
        'police': ('Polícia Judiciária', r'\bjudiciaria\b', 'pj.pt'),
    }
    name_clues = {kind for kind, (_name, pattern, _domain) in kinds.items() if re.search(pattern, normalized)}
    domain_clues = {kind for kind, (_name, _pattern, domain) in kinds.items()
                    if any(value == domain or value.endswith('.' + domain) for value in domains)}
    if len(name_clues | domain_clues) != 1 or name_clues != domain_clues:
        return {}
    kind = next(iter(name_clues))
    return {'service_entity': kinds[kind][0], 'service_entity_type': kind,
            'evidence_text': header.strip(),
            'reason': 'A cropped agency name and its official contact domain corroborate the source letterhead. This does not establish the physical service venue.'}


def _source_noncourt_agency(fields: dict[str, Any], text: str) -> tuple[str, str, dict[str, str]]:
    """An agency is a venue clue, never proof of its physical host building."""
    entity = str(fields.get('service_entity') or '').strip()
    entity_type = str(fields.get('service_entity_type') or '').strip() or classify_entity_type(entity)
    if ministerio_publico_venue_evidence(text).physical_reference:
        agency = entity if classify_entity_type(entity) == 'ministerio_publico' else 'Ministério Público'
        return agency, 'ministerio_publico', {}
    if entity and entity_type in {'gnr', 'psp', 'police', 'ministerio_publico', 'other'}:
        return entity, entity_type, {}
    if not entity and entity_type in {'gnr', 'psp', 'police', 'ministerio_publico'}:
        # The structured type can survive OCR even when the agency label is
        # cropped. Keep that clue without inventing a station or police branch.
        return {'gnr': 'Guarda Nacional Republicana',
                'psp': 'Polícia de Segurança Pública', 'police': 'Polícia',
                'ministerio_publico': 'Ministério Público'}[entity_type], entity_type, {}
    if entity or entity_type in {'court', 'ministerio_publico'}:
        return '', '', {}
    # Only a source heading supplies this fallback. Mentions inside court prose
    # (for example, instructions to notify the GNR) do not establish a venue.
    heading = re.search(r'^\s*(guarda nacional republicana|gnr\b|pol[ií]cia de seguran[cç]a p[uú]blica|psp\b|pol[ií]cia judici[aá]ria|minist[eé]rio p[uú]blico|procuradoria)[^\n]*',
                        text, re.IGNORECASE | re.MULTILINE)
    if heading and not re.search(r'\b(tribunal|juizo|ministerio publico|procuradoria)\b', normalize_text(text[:heading.start()])):
        agency = heading.group().strip()
        kind = classify_entity_type(agency)
        return agency, kind, {'service_entity': agency, 'service_entity_type': kind,
            'evidence_text': agency,
            'reason': 'The source heading names this agency. It does not establish the physical service venue.'}
    evidence = _corroborated_letterhead_agency(text)
    return evidence.get('service_entity', ''), evidence.get('service_entity_type', ''), evidence


def _city_court(city: str, preferences: dict[str, Any], directory: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    key = _city_key(city)
    mapping = preferences.get('city_courts') or {}
    candidates = [record for label, record in mapping.items()
                  if _city_key(label) == key and isinstance(record, dict)] if isinstance(mapping, dict) else []
    if not candidates:
        # A district/comarca mention or a specialized court is not a unique city match.
        for record in directory:
            name = str(record.get('name') or '')
            locality = _city_key(record.get('city') or record.get('locality'))
            name_key = _city_key(name)
            if classify_entity_type(name) != 'court':
                continue
            generic = name_key.startswith(('tribunal de ', 'tribunal judicial de ')) or 'competencia generica' in name_key
            specialized = re.search(r'\b(trabalho|familia|menores|comercio|administrativo|fiscal|execucao|central|instrucao)\b', name_key)
            if not generic or specialized:
                continue
            if locality == key or name_key.endswith(' de ' + key):
                candidates.append({'payment_entity': name, 'recipient_email': record.get('email', '')})
    if len(candidates) != 1:
        return {}, 'ambiguous_court' if candidates else 'missing_court'
    record = candidates[0]
    payer = str(record.get('payment_entity') or record.get('name') or '').strip()
    email = str(record.get('recipient_email') or record.get('email') or '').strip().lower()
    if not payer or not COURT_EMAIL.fullmatch(email):
        return {}, 'missing_court'
    return {'payment_entity': payer,
            'addressee': str(record.get('addressee') or f'Exmo. Senhor Juiz de Direito\n{payer}').strip(),
            'recipient_email': email}, 'applied'


def _apply_gnr_capture_city_default(intake: dict[str, Any], *, city: str, metadata: dict[str, Any],
                                    preferences: dict[str, Any], applied: dict[str, Any]) -> bool:
    """An explicit user policy supplies a city-level venue, not a GPS building."""
    if preferences.get('missing_gnr_venue_is_capture_city') is not True or not city:
        return False
    source_hash = str(intake.get('source_sha256') or '')
    if (not re.fullmatch(r'[a-fA-F0-9]{64}', source_hash)
            or set(intake.get('review_cleared_fields') or []).intersection({
                'service_place', 'service_place_phrase', 'service_entity', 'service_entity_type', 'source_text'})):
        return False
    gps = metadata.get('gps_city_match') or {}
    local_cities = (metadata.get('photo_metadata_city'), metadata.get('visible_metadata_city'),
                    gps.get('city') if gps.get('status') == 'matched' else '')
    if not any(value and _city_key(value) == _city_key(city) for value in local_cities):
        return False
    # A parent district or AI-inferred locality alone is not capture evidence.
    text = str(intake.get('source_text') or '')
    header = '\n'.join(text.splitlines()[:24])[:1800]
    normalized = normalize_text(header)
    boundary = re.search(r'\b(?:auto\s+de|despacho|certidao|notificacao|declaro|compareceu)\b', normalized)
    if boundary:
        header, normalized = header[:boundary.start()], normalized[:boundary.start()]
    if (not re.search(r'^\s*(?:guarda nacional republicana|gnr\b)', normalized, re.MULTILINE)
            or re.search(r'\b(?:tribunal|juizo|ministerio publico|procuradoria|psp|seguranca publica|judiciaria|'
                         r'forwarded|encaminhad[ao]|mensagem original|original message)\b|(?:^|\n)\s*>', normalized)
            or source_mentions_pj_context(intake)):
        return False
    existing = str(intake.get('service_place') or '').strip()
    if (existing and _city_key(existing) != _city_key(city)) or intake.get('service_place_phrase'):
        return False
    place = f'GNR de {city}'
    intake.update(service_place=place, service_entity=place, service_entity_type='gnr', entities_differ=True)
    intake['service_place_phrase'] = build_service_place_clause({'service_place': place}, place)
    derived = {field: intake[field] for field in (
        'service_entity', 'service_entity_type', 'entities_differ', 'service_place_phrase')}
    transport = intake.setdefault('transport', {})
    if not str(transport.get('destination') or '').strip() and 'transport.destination' not in (intake.get('review_cleared_fields') or []):
        transport['destination'] = place
        derived['transport.destination'] = place
    intake['source_location_evidence'] = {
        'source': 'gnr_capture_city_default', 'source_sha256': source_hash,
        'source_text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'city': city, 'service_place': place, 'service_entity': place, 'service_entity_type': 'gnr',
        'matched_source_phrases': [header.strip()], 'editable': True, 'applied_fields': derived,
        'reason': 'Your editable default uses the GNR named in the source and the actual capture city. '
                  'It does not identify an exact building or prove attendance or interpreting.',
    }
    applied['venue_status'] = 'gnr_capture_city_default'
    return True


def apply_photo_defaults(intake: dict[str, Any], *, preferences: dict[str, Any],
                         metadata: dict[str, Any], ai_recovery: dict[str, Any],
                         directory: list[dict[str, Any]], explicit_profile: bool = False) -> None:
    if intake.get('source_kind') != 'photo':
        return
    date_enabled = preferences.get('capture_date_is_service_date') is True
    city_enabled = preferences.get('photo_city_court') is True
    venue_enabled = preferences.get('missing_venue_is_city_court') is True
    gnr_city_enabled = preferences.get('missing_gnr_venue_is_capture_city') is True
    if not date_enabled and not city_enabled and not venue_enabled and not gnr_city_enabled:
        return
    fields = ai_recovery.get('fields') or {} if ai_recovery.get('status') == 'ok' else {}
    applied: dict[str, Any] = {}
    intake['photo_defaults_applied'] = applied
    warnings = intake.setdefault('ai_recovery', {}).setdefault('warnings', [])

    if date_enabled:
        dates = {_valid_date(value) for value in (metadata.get('exif_date'), metadata.get('picker_capture_date'),
                                                  metadata.get('picker_date_in_saved_timezone'), metadata.get('visible_metadata_date'),
                                                  fields.get('photo_metadata_date'), intake.get('photo_metadata_date'))}
        dates.discard('')
        if len(dates) == 1:
            capture = next(iter(dates))
            previous = str(intake.get('service_date') or '').strip()
            if previous and previous != capture:
                applied['original_service_date'] = previous
            intake.update(service_date=capture, photo_metadata_date=capture,
                          service_date_source='photo_metadata', photo_metadata_date_requires_confirmation=False)
            applied['service_date'] = capture
        else:
            intake.pop('service_date', None)
            intake['photo_metadata_date_requires_confirmation'] = True
            applied['date_status'] = 'ambiguous' if dates else 'missing'
            warnings.append('Your photo-date default needs one unambiguous capture date. Enter the actual date to continue.')

    if not city_enabled and not venue_enabled and not gnr_city_enabled:
        return
    gps_match = metadata.get('gps_city_match') or {}
    gps_city = gps_match.get('city', '') if gps_match.get('status') == 'matched' else ''
    cities = {_city_key(value): str(value).strip() for value in
              (metadata.get('photo_metadata_city'), metadata.get('visible_metadata_city'), fields.get('photo_metadata_city'), gps_city,
               *(metadata.get('photo_metadata_city_candidates') or []))
              if str(value or '').strip()}
    city = next(iter(cities.values())) if len(cities) == 1 else ''
    if gps_match.get('status') in {'ambiguous', 'invalid_configuration', 'invalid_gps'}:
        city = ''
    applied['photo_city'] = city
    if city and gps_city:
        applied['photo_city_source'] = 'verified_gps_area'
    elif gps_match.get('status') not in {None, 'disabled', 'missing_gps', 'outside_verified_areas'}:
        applied['gps_city_status'] = 'conflicting_city_evidence' if len(cities) > 1 else gps_match.get('status')
    # A profile deliberately selected by the user is a per-request exception.
    # Automatic/source guesses cannot supersede the user's standing city policy.
    if explicit_profile:
        if city_enabled:
            applied['routing_status'] = 'selected_profile'
        return
    selected, status = _city_court(city, preferences, directory) if city else ({}, 'ambiguous_city' if cities else 'missing_city')
    # Only absent source venues use this policy. Automatic profile guesses and
    # a bare capture city are not evidence of a physical service building.
    source_places = explicit_service_places(str(intake.get('source_text') or ''))
    mp_evidence = ministerio_publico_venue_evidence(str(intake.get('source_text') or ''))
    mp_place = mp_evidence.place
    if not source_places and mp_place:
        source_places = (mp_place,)
    ai_place = str(fields.get('service_place') or '').strip()
    building = re.search(r'\b(tribunal|ju[ií]zo|esquadra|posto|hospital|gabinete|diretoria|instala[cç][oõ]es)\b', ai_place, re.IGNORECASE)
    stations = re.findall(r'^\s*((?:Esquadra|Posto(?: Territorial)?)(?: da (?:PSP|GNR))? de [^\n]+)',
                          str(intake.get('source_text') or ''), re.IGNORECASE | re.MULTILINE)
    stations = list({_city_key(label): label for label in stations}.values())
    # A specifically named station on an appointment is supplied venue evidence;
    # a police command/district header alone still is not a physical venue.
    if venue_enabled and not source_places and len(stations) == 1:
        host = stations[0].strip().rstrip('.')
        if city and _city_key(host).endswith(' de ' + _city_key(city)):
            host = host[:-len(city)].capitalize() + city
        intake.update(service_place=host, service_entity=str(fields.get('service_entity') or host),
                      service_entity_type=classify_entity_type(host),
                      service_place_phrase=f'em diligência realizada {"na" if host.lower().startswith("esquadra") else "no"} {host}')
        intake['source_station_place'] = host
        building = True
    elif venue_enabled and not source_places and len(stations) > 1:
        applied['venue_status'] = 'ambiguous_source_venue'
        intake.update(service_place='', service_entity='', service_entity_type='', service_place_phrase='')
        warnings.append('Several named source stations appear. Confirm the actual service venue before continuing.')
    unresolved_mp_premises = mp_evidence.physical_reference and not mp_place
    if (venue_enabled or gnr_city_enabled) and not source_places and (not building or unresolved_mp_premises) and not stations:
        agency, agency_type, agency_evidence = _source_noncourt_agency(fields, str(intake.get('source_text') or ''))
        applied['venue_status'] = 'missing_noncourt_venue' if agency else status
        if agency_type == 'gnr' and _apply_gnr_capture_city_default(
                intake, city=city, metadata=metadata, preferences=preferences, applied=applied):
            clear_missing_venue_warning(intake)
        elif agency:
            if agency_evidence:
                applied['source_agency_evidence'] = agency_evidence
            intake.update(service_place='', service_place_phrase='', service_entity=agency,
                          service_entity_type=agency_type, entities_differ=True)
            warnings.append(_NONCOURT_VENUE_WARNING)
        elif selected and venue_enabled:
            place = selected['payment_entity']
            intake.update(service_place=place, service_entity=place, service_entity_type='court',
                          service_place_phrase=f'em diligência realizada no {place}', entities_differ=False)
            applied['service_place'] = place
            transport = dict(intake.get('transport') or {})
            if _city_key(transport.get('destination')) != _city_key(city):
                transport.pop('km_one_way', None)
            transport['destination'] = city
            intake['transport'] = transport
        elif venue_enabled:
            intake.update(service_place='', service_entity='', service_entity_type='', service_place_phrase='')
            warnings.append('Your missing-venue default needs a unique capture-city court. Enter the service building and city to continue.')
    if not city_enabled:
        return
    # Route as a group, so a stale profile address/key cannot restore another court.
    for field in ROUTING_FIELDS:
        intake[field] = ''
    applied['routing_status'] = status
    if selected:
        intake.update(selected)
        applied.update(selected)
        source_payer = str(fields.get('payment_entity') or '').strip()
        if source_payer and classify_entity_type(source_payer) in {'court', 'ministerio_publico'} and _city_key(source_payer) != _city_key(selected['payment_entity']):
            applied['source_payment_entity'] = source_payer
            warnings.append('The source names another court/authority. Your saved photo-city court default takes priority; edit the payment details if this request is an exception.')
        service_type = classify_entity_type(str(intake.get('service_entity') or intake.get('service_place') or ''))
        # The saved city court chooses the payer, not the physical MP venue
        # recovered from the source. Keep that distinction in the PDF.
        intake['entities_differ'] = service_type not in {'court', 'ministerio_publico'} or bool(
            service_type == 'ministerio_publico' and classify_entity_type(selected['payment_entity']) == 'court')
    else:
        warnings.append('Your photo-city court default has no unique city/court contact. Enter the paying court and recipient; the general email default will not be used.')


def apply_capture_city_answer(intake: dict[str, Any], city: str, *,
                              preferences: dict[str, Any], directory: list[dict[str, Any]]) -> None:
    """Apply one user-supplied capture city to this original source only.

    Reuse the saved policy, but never reapply its date rule or overwrite an
    existing user/source venue, routing exception, distance, or deliberate clear.
    No coordinates are interpreted and no external service is contacted.
    """
    source_hash = str(intake.get('source_sha256') or '')
    if intake.get('source_kind') != 'photo' or not re.fullmatch(r'[a-fA-F0-9]{64}', source_hash):
        raise IntakeError('The capture-city answer needs the currently reviewed original photo.')
    if preferences.get('photo_city_court') is not True:
        raise IntakeError('The saved photo-city court default is not enabled. Review the payment details directly.')
    city = ' '.join(str(city or '').split())
    if not city or len(city) > 120 or not any(character.isalpha() for character in city):
        raise IntakeError('Enter the actual city where this photo was taken.')
    cleared = set(intake.get('review_cleared_fields') or [])
    # When answering again after a source change, remove only our unchanged
    # derived values. Later manual edits and deliberate clears remain authoritative.
    for field, prior in (intake.get('photo_capture_city_applied_fields') or {}).items():
        if field in {'transport.destination', 'transport.km_one_way'}:
            transport = intake.get('transport') or {}
            key = field.split('.', 1)[1]
            if transport.get(key) == prior and field not in cleared:
                transport.pop(key, None)
        elif field not in cleared and intake.get(field) == prior:
            intake.pop(field, None)
    previous = copy.deepcopy(intake.get('photo_defaults_applied') or {})
    proposed = copy.deepcopy(intake)
    recovery = copy.deepcopy(intake.get('ai_recovery') or {})
    if isinstance(recovery.get('fields'), dict):
        recovery['fields'].pop('photo_metadata_city', None)
    apply_photo_defaults(proposed, preferences={**preferences, 'capture_date_is_service_date': False},
                         metadata={'photo_metadata_city': city}, ai_recovery=recovery, directory=directory,
                         explicit_profile=(intake.get('auto_profile') or {}).get('mode') == 'explicit_profile')
    applied = proposed.get('photo_defaults_applied') or {}
    changes: dict[str, Any] = {}

    def supply(field: str) -> None:
        value = proposed.get(field)
        if value not in (None, ''):
            intake[field] = copy.deepcopy(value)
            changes[field] = copy.deepcopy(value)

    routing_override = any(str(intake.get(field) or '').strip() for field in ROUTING_FIELDS)
    if not routing_override and not cleared.intersection(ROUTING_FIELDS):
        for field in ROUTING_FIELDS:
            supply(field)
    else:
        for field in ('payment_entity', 'addressee', 'recipient_email'):
            applied.pop(field, None)
        applied['routing_status'] = 'manual_override'
    venue_fields = ('service_place', 'service_entity', 'service_entity_type', 'service_place_phrase', 'entities_differ')
    has_venue = any(str(intake.get(field) or '').strip() for field in ('service_place', 'service_entity', 'service_place_phrase'))
    gnr_proof = proposed.get('source_location_evidence') or {}
    source_fields = recovery.get('fields') or {}
    source_agency, _source_type, _agency_evidence = _source_noncourt_agency(source_fields, str(intake.get('source_text') or ''))
    current_agency = str(intake.get('service_entity') or '').strip()
    gnr_agency_unchanged = not current_agency or _city_key(current_agency) == _city_key(source_agency)
    gnr_default = bool(applied.get('venue_status') == 'gnr_capture_city_default'
                       and gnr_proof.get('source') == 'gnr_capture_city_default'
                       and gnr_agency_unchanged and intake.get('service_entity_type') in (None, '', 'gnr')
                       and not any(str(intake.get(field) or '').strip()
                                   for field in ('service_place', 'service_place_phrase')))
    if ((applied.get('service_place') and not has_venue) or gnr_default) and not cleared.intersection(venue_fields):
        for field in venue_fields:
            supply(field)
        if gnr_default:
            intake['source_location_evidence'] = copy.deepcopy(gnr_proof)
            clear_missing_venue_warning(intake)
        transport = intake.setdefault('transport', {})
        if not str(transport.get('destination') or '').strip() and 'transport.destination' not in cleared:
            destination = str((proposed.get('transport') or {}).get('destination') or city)
            transport['destination'] = destination
            changes['transport.destination'] = destination
            if transport.get('km_one_way') in (None, ''):
                # Do not let an auto-selected service profile restore its old
                # destination's distance; the personal lookup uses this city.
                intake['source_transport_distance_pending'] = True
    else:
        applied.pop('service_place', None)
        # An existing station/source venue stays authoritative; no court venue
        # default should subsequently synchronize or clear it during re-review.
        if has_venue:
            applied.pop('venue_status', None)
    previous.update(applied)
    for field in ('payment_entity', 'recipient_email', 'service_place'):
        if field not in applied:
            previous.pop(field, None)
    previous['photo_city'] = city
    previous['photo_city_source'] = 'user_confirmed_capture_city'
    intake.update(photo_capture_city=city, photo_capture_city_source_sha256=source_hash,
                  photo_capture_city_applied_fields=changes, photo_defaults_applied=previous)


def apply_saved_court_label(intake: dict[str, Any], preferences: dict[str, Any], *, explicit_profile: bool = False) -> None:
    """Use an exact saved ordinary-court label, without changing source routing."""
    if explicit_profile or intake.get('source_kind') != 'notification_pdf':
        return
    mapping = preferences.get('city_courts')
    if not isinstance(mapping, dict):
        return
    recipient = str(intake.get('recipient_email') or '').strip().lower()
    matches = [(city, record) for city, record in mapping.items() if isinstance(record, dict)
               and recipient and recipient == str(record.get('recipient_email') or record.get('email') or '').strip().lower()]
    if len(matches) != 1:
        return
    city, record = matches[0]
    label = str(record.get('payment_entity') or record.get('name') or '').strip()
    city_key = _city_key(city)
    if _city_key(label) != 'tribunal de ' + city_key:
        return
    def same_ordinary_court(value: Any) -> bool:
        text = _city_key(value)
        specialized = re.search(r'\b(trabalho|familia|menores|comercio|administrativo|fiscal|execucao|central|instrucao|criminal|civel)\b', text)
        return not specialized and text.startswith(('tribunal ', 'juizo ')) and text.endswith(' de ' + city_key)
    def grounded(value: Any) -> bool:
        words = lambda text: ' '.join(re.sub(r'[^\w]+', ' ', _city_key(text)).split())
        return bool(words(value)) and words(value) in words(intake.get('source_text'))
    payer = str(intake.get('payment_entity') or '')
    if not same_ordinary_court(payer) or not grounded(payer):
        return
    before = {'payment_entity': payer, 'addressee': str(intake.get('addressee') or '')}
    intake.update(payment_entity=label, addressee=str(record.get('addressee') or f'Exmo. Senhor Juiz de Direito\n{label}'))
    for field in ('service_entity', 'service_place'):
        value = intake.get(field)
        court_prefix = str(value or '').split(',', 1)[0].strip()
        if same_ordinary_court(court_prefix) and grounded(court_prefix):
            before[field] = value
            intake[field] = label
    if 'service_place' in before:
        before['service_place_phrase'] = intake.get('service_place_phrase', '')
        intake['service_place_phrase'] = f'em diligência realizada no {label}'
    intake['court_label_preference'] = {'label': label, 'original_fields': before}


def preserve_photo_routing(original: dict[str, Any], merged: dict[str, Any]) -> None:
    """Profile re-review must not reintroduce a removed payer or recipient."""
    applied = original.get('photo_defaults_applied')
    if not isinstance(applied, dict):
        return
    if 'service_date' in original and not original.get('service_date'):
        merged['service_date'] = ''
        merged['photo_metadata_date_requires_confirmation'] = True
    if 'routing_status' in applied:
        for field in ROUTING_FIELDS:
            merged[field] = original.get(field, '')
    if 'service_place' in applied or 'venue_status' in applied:
        for field in ('service_place', 'service_place_phrase', 'service_entity', 'service_entity_type', 'entities_differ'):
            merged[field] = original.get(field, '')


def clear_missing_venue_warning(intake: dict[str, Any]) -> None:
    """Remove only the app's unresolved-venue warning after a venue is supplied."""
    applied = intake.get('photo_defaults_applied') or {}
    if isinstance(applied, dict) and applied.get('venue_status') == 'missing_noncourt_venue':
        applied.pop('venue_status', None)
    recovery = intake.get('ai_recovery') or {}
    if isinstance(recovery, dict) and isinstance(recovery.get('warnings'), list):
        recovery['warnings'] = [warning for warning in recovery['warnings'] if warning != _NONCOURT_VENUE_WARNING]


def reconcile_photo_venue_edit(intake: dict[str, Any]) -> None:
    """Drop dependent default venue fields when the user edits one of them."""
    _reconcile_inferred_venue_edit(intake)
    applied = intake.get('photo_defaults_applied') or {}
    if (isinstance(applied, dict) and applied.get('venue_status') == 'missing_noncourt_venue'
            and str(intake.get('service_place') or '').strip()):
        place = str(intake['service_place']).strip()
        entity = 'Polícia Judiciária' if source_mentions_pj_context(intake) else place
        kind = classify_entity_type(entity)
        intake.update(service_entity=entity, service_entity_type=kind,
                      entities_differ=kind not in {'court', 'ministerio_publico'} or bool(
                          kind == 'ministerio_publico'
                          and classify_entity_type(str(intake.get('payment_entity') or '')) == 'court'))
        clear_missing_venue_warning(intake)
    default = applied.get('service_place') if isinstance(applied, dict) else ''
    if not default:
        return
    place = str(intake.get('service_place', default) or '').strip()
    entity = str(intake.get('service_entity', default) or '').strip()
    previous = str(intake.get('photo_venue_last_value') or default)
    if place == previous and entity == previous:
        return
    aliases_changed = False
    if place != previous and entity == previous:
        entity = place
        aliases_changed = True
    elif entity != previous and place == previous:
        place = entity
        aliases_changed = True
    intake.update(service_place=place, service_entity=entity)
    if intake.get('service_place_phrase') == f'em diligência realizada no {default}':
        intake['service_place_phrase'] = ''
    if not place and not entity:
        intake.update(service_entity_type='', entities_differ=False)
    elif aliases_changed or intake.get('service_entity_type') in ('court', '', None):
        entity_type = classify_entity_type(entity or place)
        intake.update(service_entity_type=entity_type, entities_differ=entity_type not in {'court', 'ministerio_publico'})
    if place == entity:
        intake['photo_venue_last_value'] = place


def _reconcile_inferred_venue_edit(intake: dict[str, Any]) -> None:
    """Update only untouched dependencies of a source-bound venue default."""
    proof = intake.get('source_location_evidence') or {}
    if (not isinstance(proof, dict) or proof.get('source') not in {'verified_gps_source_venue', 'gnr_capture_city_default'}
            or proof.get('source_sha256') != intake.get('source_sha256')):
        return
    derived = proof.get('applied_fields') or {}
    if not isinstance(derived, dict):
        return
    previous = proof.get('last_venue', proof.get('service_place'))
    place = str(intake.get('service_place') or '').strip()
    if place == previous:
        return
    entity = 'Polícia Judiciária' if place and source_mentions_pj_context(intake) else place
    kind = classify_entity_type(entity) if entity else ''
    updates = {'service_entity': entity, 'service_entity_type': kind,
               'entities_differ': bool(kind and (kind not in {'court', 'ministerio_publico'} or (
                   kind == 'ministerio_publico' and classify_entity_type(str(intake.get('payment_entity') or '')) == 'court'))),
               'service_place_phrase': build_service_place_clause({'service_place': place}, entity) if place else ''}
    for field, value in updates.items():
        if field in derived and intake.get(field) == derived[field]:
            intake[field] = value
            derived[field] = value
    transport = intake.get('transport') or {}
    if (isinstance(transport, dict) and 'transport.destination' in derived
            and transport.get('destination') == derived['transport.destination']):
        transport['destination'] = place
        derived['transport.destination'] = place
        if ('transport.km_one_way' in derived
                and transport.get('km_one_way') == derived['transport.km_one_way']):
            transport['km_one_way'] = ''
            derived.pop('transport.km_one_way', None)
            intake['source_transport_distance_pending'] = True
    proof['last_venue'] = place
