"""Saved photo policy, kept separate from OCR facts and provider configuration."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from scripts.entity_rules import classify_entity_type, normalize_text
from scripts.generate_pdf import IntakeError
from scripts.source_parsing import explicit_service_places

ROUTING_FIELDS = ('payment_entity', 'addressee', 'recipient_email', 'court_email',
                  'court_email_key', 'recipient_override_reason', 'court_email_override_reason')
COURT_EMAIL = re.compile(r'[A-Z0-9._%+\-]+@tribunais\.org\.pt', re.IGNORECASE)


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


def apply_photo_defaults(intake: dict[str, Any], *, preferences: dict[str, Any],
                         metadata: dict[str, Any], ai_recovery: dict[str, Any],
                         directory: list[dict[str, Any]], explicit_profile: bool = False) -> None:
    if intake.get('source_kind') != 'photo':
        return
    date_enabled = preferences.get('capture_date_is_service_date') is True
    city_enabled = preferences.get('photo_city_court') is True
    venue_enabled = preferences.get('missing_venue_is_city_court') is True
    if not date_enabled and not city_enabled and not venue_enabled:
        return
    fields = ai_recovery.get('fields') or {} if ai_recovery.get('status') == 'ok' else {}
    applied: dict[str, Any] = {}
    intake['photo_defaults_applied'] = applied
    warnings = intake.setdefault('ai_recovery', {}).setdefault('warnings', [])

    if date_enabled:
        dates = {_valid_date(value) for value in (metadata.get('exif_date'), metadata.get('visible_metadata_date'),
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

    if not city_enabled and not venue_enabled:
        return
    cities = {_city_key(value): str(value).strip() for value in
              (metadata.get('photo_metadata_city'), metadata.get('visible_metadata_city'), fields.get('photo_metadata_city'))
              if str(value or '').strip()}
    city = next(iter(cities.values())) if len(cities) == 1 else ''
    applied['photo_city'] = city
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
    if venue_enabled and not source_places and not building and not stations:
        applied['venue_status'] = status
        if selected:
            place = selected['payment_entity']
            intake.update(service_place=place, service_entity=place, service_entity_type='court',
                          service_place_phrase=f'em diligência realizada no {place}', entities_differ=False)
            applied['service_place'] = place
            transport = dict(intake.get('transport') or {})
            if _city_key(transport.get('destination')) != _city_key(city):
                transport.pop('km_one_way', None)
            transport['destination'] = city
            intake['transport'] = transport
        else:
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
        intake['entities_differ'] = classify_entity_type(str(intake.get('service_entity') or intake.get('service_place') or '')) not in {'court', 'ministerio_publico'}
    else:
        warnings.append('Your photo-city court default has no unique city/court contact. Enter the paying court and recipient; the general email default will not be used.')


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
        if same_ordinary_court(value) and grounded(value):
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


def reconcile_photo_venue_edit(intake: dict[str, Any]) -> None:
    """Drop dependent default venue fields when the user edits one of them."""
    applied = intake.get('photo_defaults_applied') or {}
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
