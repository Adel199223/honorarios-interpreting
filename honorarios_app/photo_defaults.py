"""Saved photo policy, kept separate from OCR facts and provider configuration."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from scripts.entity_rules import classify_entity_type, normalize_text
from scripts.generate_pdf import IntakeError

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
    if not date_enabled and not city_enabled:
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

    if not city_enabled:
        return
    cities = {_city_key(value): str(value).strip() for value in
              (metadata.get('photo_metadata_city'), metadata.get('visible_metadata_city'), fields.get('photo_metadata_city'))
              if str(value or '').strip()}
    city = next(iter(cities.values())) if len(cities) == 1 else ''
    applied['photo_city'] = city
    # A profile deliberately selected by the user is a per-request exception.
    # Automatic/source guesses cannot supersede the user's standing city policy.
    if explicit_profile:
        applied['routing_status'] = 'selected_profile'
        return
    selected, status = _city_court(city, preferences, directory) if city else ({}, 'ambiguous_city' if cities else 'missing_city')
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
