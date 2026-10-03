"""Editable venue proposals from specific source headings and verified local GPS.

No geocoding, provider calls, state writes or intake mutation. A successful match
is derived evidence for normal review; it does not establish attendance or work.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from scripts.entity_rules import classify_entity_type, normalize_text
from scripts.source_parsing import explicit_service_places
from .gps_city import _distance_m, _number

MAX_VERIFIED_VENUES = 100
MAX_VENUE_RADIUS_M = 200
_AGENCIES = {
    'gnr': ('guarda nacional republicana',),
    'psp': ('policia de seguranca publica',),
    'police': ('policia judiciaria',),
    'ministerio_publico': ('ministerio publico',),
}


def _normalized(value: str) -> str:
    return ' '.join(re.sub(r'[^\w\s]', ' ', normalize_text(value)).split())


def _text(value: Any, limit: int) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and any(char.isalpha() for char in value)
            and not any(ord(char) < 32 for char in value))


def _contains(text: str, phrase: str) -> bool:
    return ' ' + phrase + ' ' in ' ' + text + ' '


def _entity_kind(value: str) -> str:
    kind = classify_entity_type(value)
    # DIAP is an MP unit; proposals still require the full MP source heading.
    if kind == 'other' and re.match(r'^(?:diap\b|departamento de investigacao e acao penal\b)', _normalized(value)):
        return 'ministerio_publico'
    return kind


def _url(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 2000 or any(char.isspace() or ord(char) < 32 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == 'https' and bool(parsed.hostname) and parsed.username is None and parsed.password is None
    except ValueError:
        return False


def _venue(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if any(not _text(value.get(key), limit) for key, limit in (
        ('id', 120), ('city', 120), ('service_entity', 240), ('service_place', 300))):
        return None
    kind = value.get('service_entity_type')
    if not isinstance(kind, str) or kind not in _AGENCIES or _entity_kind(value['service_entity']) != kind:
        return None
    if (not _number(value.get('latitude'), -90, 90) or not _number(value.get('longitude'), -180, 180)
            or not _number(value.get('radius_m'), 0, MAX_VENUE_RADIUS_M) or value['radius_m'] == 0):
        return None
    phrases = value.get('required_source_phrases')
    urls = value.get('source_urls')
    if (not isinstance(phrases, list) or not 2 <= len(phrases) <= 12
            or any(not _text(phrase, 160) for phrase in phrases)
            or not isinstance(urls, list) or not 1 <= len(urls) <= 5 or not all(_url(url) for url in urls)):
        return None
    normalized = [_normalized(phrase) for phrase in phrases]
    city = _normalized(value['city'])
    # An agency and a city alone must never become a verified physical venue.
    agency_phrases = _AGENCIES[kind]
    if (not any(phrase in normalized for phrase in agency_phrases)
            or not any(len(phrase) >= 8 and phrase not in (*agency_phrases, city) for phrase in normalized)
            or not any(_contains(phrase, city) for phrase in normalized)
            or not _contains(_normalized(value['service_place']), city)
            or len(set(normalized)) != len(normalized)):
        return None
    return {key: value[key] for key in ('id', 'city', 'service_entity', 'service_entity_type', 'service_place',
                                      'latitude', 'longitude', 'radius_m')} | {
        'required_source_phrases': normalized, 'source_urls': list(urls)}


def _source_header(text: str) -> str:
    header = '\n'.join(text.splitlines()[:24])[:1800]
    # A quoted agency contact in a letter or email is not the source issuer.
    if re.search(r'\b(?:forwarded|encaminhad[ao]|mensagem original|original message)\b|'
                 r'(?:^|\n)\s*(?:(?:de|from|para|to|assunto|subject|fwd|fw)\s*:|>)', normalize_text(header)):
        return ''
    boundary = re.search(r'\b(?:auto\s+de|despacho|certidao|notificacao|declaro|declarou|compareceu)\b', normalize_text(header))
    if boundary:
        header = header[:boundary.start()]
    return _normalized(header)


def propose_verified_source_venue(intake: dict[str, Any], *, metadata: dict[str, Any],
                                  preferences: dict[str, Any]) -> dict[str, Any]:
    """Return a proposal only for one missing venue with corroborated source/GPS.

    The private catalog is explicitly verified configuration, not a nearest-place
    database. One invalid entry or more than one matching venue fails closed.
    Calculate after OCR/GPS city evidence, then apply before review only if the
    ordinary source/photo defaults did not establish a real physical location.
    The caller must retain this provenance and existing review/freshness guards.
    """
    if not all(isinstance(value, dict) for value in (intake, metadata, preferences)):
        return {}
    catalog = preferences.get('verified_gps_venues', [])
    if not isinstance(catalog, list) or not 1 <= len(catalog) <= MAX_VERIFIED_VENUES:
        return {}
    venues = [_venue(value) for value in catalog]
    if any(value is None for value in venues) or len({value['id'] for value in venues}) != len(venues):
        return {}
    profile = intake.get('auto_profile') or {}
    if not isinstance(profile, dict):
        return {}
    if (intake.get('source_kind') != 'photo' or intake.get('service_place') or intake.get('service_place_phrase')
            or profile.get('mode') == 'explicit_profile'
            or not re.fullmatch(r'[0-9a-f]{64}', str(intake.get('source_sha256') or ''))):
        return {}
    cleared = intake.get('review_cleared_fields') or []
    if not isinstance(cleared, list) or any(field in cleared for field in (
        'service_place', 'service_place_phrase', 'service_entity', 'service_entity_type', 'source_text')):
        return {}
    gps = metadata.get('gps_coordinates')
    if (not isinstance(gps, dict) or gps.get('source') != 'exif_gps'
            or not _number(gps.get('latitude'), -90, 90) or not _number(gps.get('longitude'), -180, 180)):
        return {}
    recovery = intake.get('ai_recovery') or {}
    if not isinstance(recovery, dict):
        return {}
    fields = recovery.get('fields') or {}
    if not isinstance(fields, dict):
        return {}
    text = str(intake.get('source_text') or recovery.get('raw_visible_text') or '')
    # Printed service locations take precedence, including a different host.
    if explicit_service_places(text):
        return {}
    header = _source_header(text)
    source_kinds = {kind for kind, phrases in _AGENCIES.items() if any(_contains(header, phrase) for phrase in phrases)}
    named_kind = _entity_kind(str(intake.get('service_entity') or ''))
    kind = intake.get('service_entity_type') or named_kind
    if (kind == 'court' and profile.get('mode') == 'auto_fallback'
            and intake.get('service_entity') and named_kind in _AGENCIES and source_kinds == {named_kind}):
        # Generic fallback profiles can retain a court type after OCR names the
        # agency. Only its own matching name and heading may correct that type.
        kind = named_kind
    if not isinstance(kind, str) or kind not in _AGENCIES or source_kinds != {kind}:
        return {}
    if intake.get('service_entity') and named_kind not in {kind, 'other', ''}:
        return {}
    # A court heading quoting police/MP material is not an agency venue source.
    agency_start = min(header.find(phrase) for phrase in _AGENCIES[kind] if _contains(header, phrase))
    if re.search(r'\b(?:tribunal|juizo)\b', header[:agency_start]):
        return {}
    gps_city = metadata.get('gps_city_match') or {}
    if not isinstance(gps_city, dict) or gps_city.get('status') not in (None, 'disabled', 'outside_verified_areas', 'matched'):
        return {}
    if gps_city.get('status') == 'matched' and not _text(gps_city.get('city'), 120):
        return {}
    capture_cities = metadata.get('photo_metadata_city_candidates') or []
    if not isinstance(capture_cities, list):
        return {}
    named_cities = [metadata.get('photo_metadata_city'), metadata.get('visible_metadata_city'),
                    fields.get('photo_metadata_city'), intake.get('photo_capture_city'), *capture_cities]
    if gps_city.get('status') == 'matched':
        named_cities.append(gps_city.get('city'))
    if any(value is not None and not isinstance(value, str) for value in named_cities):
        return {}
    cities = {_normalized(value) for value in named_cities if value and value.strip()}
    matches = []
    for venue in venues:
        if (venue['service_entity_type'] != kind or any(city != _normalized(venue['city']) for city in cities)
                or not all(_contains(header, phrase) for phrase in venue['required_source_phrases'])):
            continue
        distance = _distance_m(gps['latitude'], gps['longitude'], venue)
        if distance <= venue['radius_m']:
            matches.append((venue, round(distance, 2)))
    if len(matches) != 1:
        return {}
    venue, distance = matches[0]
    return {key: venue[key] for key in ('service_place', 'service_entity', 'service_entity_type')} | {
        'entities_differ': kind not in {'court', 'ministerio_publico'},
        'source_location_evidence': {
            'source': 'verified_gps_source_venue', 'source_sha256': intake['source_sha256'],
            'source_text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'source_agency_type': kind,
            'service_entity': venue['service_entity'], 'service_entity_type': kind,
            'venue_id': venue['id'], 'city': venue['city'], 'service_place': venue['service_place'],
            'distance_m': distance, 'radius_m': venue['radius_m'],
            'source_urls': list(venue['source_urls']), 'matched_source_phrases': list(venue['required_source_phrases']),
            'editable': True,
            'reason': 'Editable venue default inferred from the specific source heading and nearby original photo GPS. '
                      'This is not a printed venue or proof of attendance or interpreting.',
        },
    }
