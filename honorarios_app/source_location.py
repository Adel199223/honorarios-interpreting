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
from .gps_city import _distance_m, _number, _geometry_metadata

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
    geometry = _geometry_metadata(value)
    if geometry is None:
        return None
    city_basis = value.get('source_city_basis')
    if ('source_city_basis' in value and (city_basis != 'verified_gps' or kind not in {'ministerio_publico', 'police'}
            or geometry.get('geometry_basis') != 'user_confirmed_photo_venue')):
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
            or (city_basis != 'verified_gps' and not any(_contains(phrase, city) for phrase in normalized))
            or not _contains(_normalized(value['service_place']), city)
            or len(set(normalized)) != len(normalized)):
        return None
    return {key: value[key] for key in ('id', 'city', 'service_entity', 'service_entity_type', 'service_place',
                                      'latitude', 'longitude', 'radius_m')} | {
        'required_source_phrases': normalized, 'source_urls': list(urls), **geometry,
        **({'source_city_basis': city_basis} if city_basis else {})}


def _recurring_header(text: str, venue: dict[str, Any]) -> dict[str, Any]:
    """Own issuer/unit evidence; city comes from a separately matched GPS area."""
    raw_header = _source_header_text(text)
    lines = raw_header.splitlines()
    kind, city = venue['service_entity_type'], _normalized(venue['city'])
    agency_phrase = _AGENCIES[kind][0]
    institution = r'procuradoria da republica da comarca de (?P<city>\w+(?: \w+)*)'
    agency_pattern = (r'ministerio publico(?: procuradoria da(?: republica da comarca de \w+(?: \w+)*)?)?'
                      if kind == 'ministerio_publico' else re.escape(agency_phrase))
    agency = next(((i, raw) for i, raw in enumerate(lines)
                   if re.fullmatch(agency_pattern, _normalized(raw))), None)
    corroboration = {}
    if agency is None and kind == 'ministerio_publico':
        corroboration = _corroborated_mp_heading(raw_header, venue['city'])
        if corroboration:
            agency = next((i, raw) for i, raw in enumerate(lines)
                          if raw.strip() == corroboration['raw_excerpts'][0])
    if agency is None:
        return {}
    start, agency_raw = agency
    # Case/reference can precede a cropped issuer. A digital-signature preamble
    # is one line or two bounded metadata lines, never arbitrary narrative.
    prefix = [raw for raw in lines[:start] if _normalized(raw)]
    if prefix and re.fullmatch(r'Assinado em \d{2}[-/]\d{2}[-/]\d{4}, por '
            r'[\w .,-]{1,200}\bProcurador(?:a)? da Rep[uú]blica', prefix[0].strip(), re.IGNORECASE):
        prefix = prefix[1:]
    elif len(prefix) >= 2 and re.fullmatch(
            r'Assinado em \d{2}[-/]\d{2}[-/]\d{4}, por', prefix[0].strip(), re.IGNORECASE):
        if (len(prefix[1]) > 240 or not re.fullmatch(
                r'[\w .,-]+\bProcurador(?:a)? da Rep[uú]blica', prefix[1].strip(), re.IGNORECASE)):
            return {}
        prefix = prefix[2:]
    for raw in prefix:
        if _normalized(raw) in {'s r', 'ministerio da justica'}:
            continue
        if not re.fullmatch(r'\s*(?:Processo|Refer[eê]ncia)\s*:\s*[0-9][0-9A-Za-z/. -]{0,100}\s*', raw, re.IGNORECASE):
            return {}
    issuer = []
    for raw in lines[start:]:
        if issuer and re.search(r'\b\d+\s*/\s*\d{2}\s*\.\s*\d?[A-Za-z]', raw):
            break
        issuer.append(raw)
    if any(raw.lstrip().startswith(('"', "'", '“', '”', '«', '»', '‘', '’', '>')) for raw in issuer):
        return {}
    header = _normalized('\n'.join(issuer))
    source_kinds = {name for name, phrases in _AGENCIES.items()
                    if any(_contains(header, phrase) for phrase in phrases)}
    if corroboration:
        source_kinds.add('ministerio_publico')
    abbreviated = {'gnr': r'\bgnr\b|\bnacional republicana\b',
                   'psp': r'\bpsp\b|\bseguranca publica\b',
                   'police': r'\bpj\b|\bjudiciaria\b'}
    source_kinds.update(name for name, pattern in abbreviated.items() if re.search(pattern, header))
    if source_kinds != {kind}:
        return {}
    for raw in issuer:
        line = _normalized(raw)
        match = re.fullmatch(r'(?:ministerio publico )?' + institution, line)
        if match and match['city'] != city:
            return {}
    units = []
    phrases = [phrase for phrase in venue['required_source_phrases'] if phrase not in _AGENCIES[kind]]
    for raw in issuer[1:]:
        line = _normalized(raw)
        if kind == 'ministerio_publico':
            unit = re.fullmatch(r'(?:(?:procuradoria do )?juizo )?local criminal'
                r'(?: (?:[0-9]{1,2}[aª]? )?(?:sec|seccao)(?: (?:de )?inqueritos)?)?'
                r'(?: de (?P<city>\w+(?: \w+)*))?', line)
        else:
            unit = next((match for phrase in phrases if (match := re.fullmatch(
                re.escape(phrase) + r'(?: de (?P<city>\w+(?: \w+)*))?', line))), None)
        if unit:
            if unit['city'] and unit['city'] != city:
                return {}
            units.append(raw.strip())
        elif not units and line and line not in {'s r', 'ministerio da justica'}:
            # Institution context may separate the own agency and unit. Prose,
            # quoted contacts and a transcription directive cannot do so.
            if not (kind == 'ministerio_publico' and (line == 'procuradoria da'
                    or re.fullmatch(institution, line))):
                return {}
    if len(units) != 1 or not all(_contains(header, phrase) for phrase in phrases):
        return {}
    # Every configured non-agency phrase must belong to this actual unit line.
    if not all(_contains(_normalized(units[0]), phrase) for phrase in phrases):
        return {}
    return {'basis': 'own_agency_unit_heading', 'city_basis': 'verified_gps',
            'raw_excerpts': [agency_raw.strip(), units[0]],
            **({'source_agency_corroboration': corroboration} if corroboration else {})}


def _recurring_proposal(intake: dict[str, Any], metadata: dict[str, Any], venue: dict[str, Any],
                        fields: dict[str, Any], text: str, fallback: dict[str, Any] | None) -> dict[str, Any]:
    gps_city = metadata.get('gps_city_match') or {}
    if (not isinstance(gps_city, dict) or gps_city.get('status') != 'matched'
            or _normalized(str(gps_city.get('city') or '')) != _normalized(venue['city'])):
        return {}
    cities = metadata.get('photo_metadata_city_candidates') or []
    if not isinstance(cities, list):
        return {}
    cities = [*cities, metadata.get('photo_metadata_city'), metadata.get('visible_metadata_city'),
              fields.get('photo_metadata_city'), intake.get('photo_capture_city')]
    if any(city is not None and (not isinstance(city, str)
            or (city.strip() and _normalized(city) != _normalized(venue['city']))) for city in cities):
        return {}
    heading = _recurring_header(text, venue)
    if not heading:
        return {}
    kind = venue['service_entity_type']
    entity = str(intake.get('service_entity') or '')
    named_kind = _entity_kind(entity)
    current_kind = intake.get('service_entity_type') or named_kind
    untouched = (isinstance(fallback, dict) and (intake.get('auto_profile') or {}).get('mode') == 'auto_fallback'
                 and all(str(intake.get(key) or '') == str(fallback.get(key) or '')
                         for key in ('service_entity', 'service_entity_type'))
                 and not any(fields.get(key) for key in ('service_entity', 'service_entity_type')))
    if current_kind != kind and not untouched:
        return {}
    corroboration = heading.get('source_agency_corroboration') or {}
    cropped_entity = bool(corroboration and entity.strip() == corroboration['raw_excerpts'][0])
    grounded_entity = bool(entity and any(_normalized(entity) == _normalized(raw)
                                        for raw in heading['raw_excerpts']))
    if entity and named_kind not in {kind, 'other', ''} and not untouched and not cropped_entity and not grounded_entity:
        return {}
    if entity and not untouched:
        if named_kind in {'other', ''} and not grounded_entity:
            return {}
        if (named_kind == kind and not _contains(_normalized(text), _normalized(entity))
                and _normalized(entity) not in _AGENCIES[kind]):
            return {}
    gps = metadata['gps_coordinates']
    distance = _distance_m(gps['latitude'], gps['longitude'], venue)
    if distance > venue['radius_m']:
        return {}
    # Keep recognized source wording, including its unit. A cropped issuer can
    # establish only a separately labelled generic MP agency, not an invented unit.
    entity = (entity if entity and (named_kind == kind or (grounded_entity and not cropped_entity)) else
              'Ministério Público' if kind == 'ministerio_publico' else venue['service_entity'])
    proof = {'source': 'verified_gps_source_venue', 'source_sha256': intake['source_sha256'],
             'source_text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
             'source_agency_type': kind, 'service_entity': entity, 'service_entity_type': kind,
             'venue_id': venue['id'], 'city': venue['city'], 'service_place': venue['service_place'],
             'distance_m': round(distance, 2), 'radius_m': venue['radius_m'],
             'source_urls': list(venue['source_urls']),
             'matched_source_phrases': [phrase for phrase in venue['required_source_phrases']
                                       if _contains(_normalized('\n'.join(heading['raw_excerpts'])), phrase)],
             **{key: venue[key] for key in ('geometry_basis', 'confirmation_source_sha256', 'confirmation_date')},
             'source_city_basis': 'verified_gps', 'source_heading_evidence': heading,
             **({'source_agency_corroboration': corroboration} if corroboration else {}),
             'editable': True,
             'reason': 'Editable reusable venue default from an own agency/unit heading and current original photo GPS '
                       'at a previously user-confirmed venue point. GPS supplies the city; it is not an invented printed city. '
                       'Reference links provide location context; the point/venue association is user-confirmed, not a surveyed footprint. '
                       'This is not a printed venue or proof of attendance or interpreting.'}
    return {'service_place': venue['service_place'], 'service_entity': entity, 'service_entity_type': kind,
            'entities_differ': kind not in {'court', 'ministerio_publico'}, 'source_location_evidence': proof}


def _source_header_text(text: str) -> str:
    header = '\n'.join(text.splitlines()[:24])[:1800]
    # A quoted agency contact in a letter or email is not the source issuer.
    if re.search(r'\b(?:forwarded|encaminhad[ao]|mensagem original|original message)\b|'
                 r'(?:^|\n)\s*(?:(?:de|from|para|to|assunto|subject|fwd|fw)\s*:|>)', normalize_text(header)):
        return ''
    boundary = re.search(r'\b(?:auto\s+de|despacho|certidao|notificacao|'
                         r'notifique|notificar|remeta|remeter|junte|juntar|declaro|declarou|compareceu)\b',
                         normalize_text(header))
    if boundary:
        header = header[:boundary.start()]
    return header


def _corroborated_mp_heading(header: str, city: str) -> dict[str, Any]:
    """Two own issuer lines can identify MP without inventing its full label.

    This does not identify a physical building. A separate unique verified GPS
    venue is still mandatory, and every non-agency catalog phrase stays literal.
    """
    if re.search(r'\b(?:gnr|psp|pj|judiciaria|nacional republicana|seguranca publica)\b', _normalized(header)):
        return {}
    institutions, units = [], []
    lines = header.splitlines()
    for index, raw in enumerate(lines):
        line = _normalized(raw)
        institution = re.fullmatch(
            r'(?:procuradoria|curadoria|radoria) da republica da comarca de (?P<city>\w+(?: \w+)*)', line)
        unit = re.fullmatch(
            r'(?:(?:procuradoria do )?juizo )?local criminal '
            r'(?:[0-9]{1,2}[aª]? )?(?:sec|seccao) (?:de )?inqueritos de (?P<city>\w+(?: \w+)*)', line)
        if institution:
            if raw.lstrip().startswith(('"', "'", '“', '”', '«', '»', '‘', '’')):
                return {}
            institutions.append((institution['city'], raw.strip(), index))
        if unit:
            if raw.lstrip().startswith(('"', "'", '“', '”', '«', '»', '‘', '’')):
                return {}
            units.append((unit['city'], raw.strip(), index))
    if (len(institutions) != 1 or len(units) != 1
            or institutions[0][0] != _normalized(city) or units[0][0] != _normalized(city)):
        return {}
    # Case/reference labels can precede the issuer in a cover. Narrative or
    # quoted body text cannot establish that these are the source's own lines.
    for raw in lines[:institutions[0][2]]:
        if not _normalized(raw) or _normalized(raw) in {'s r', 'ministerio publico', 'ministerio da justica'}:
            continue
        if not re.fullmatch(r'\s*(?:Processo|Refer[eê]ncia)\s*:\s*[0-9][0-9A-Za-z/. -]{0,100}\s*', raw, re.IGNORECASE):
            return {}
    return {'basis': 'corroborated_procuradoria_heading', 'derived_agency_type': 'ministerio_publico',
            'city': city, 'raw_excerpts': [institutions[0][1], units[0][1]]}


def propose_verified_source_venue(intake: dict[str, Any], *, metadata: dict[str, Any],
                                  preferences: dict[str, Any],
                                  fallback_defaults: dict[str, Any] | None = None) -> dict[str, Any]:
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
    if any(venue.get('source_city_basis') == 'verified_gps' for venue in venues):
        # Check every configured venue independently, then keep the existing
        # unique-match contract across legacy and opt-in rules alike.
        proposals = []
        for venue in venues:
            if venue.get('source_city_basis') == 'verified_gps':
                proposal = _recurring_proposal(intake, metadata, venue, fields, text, fallback_defaults)
            else:
                proposal = propose_verified_source_venue(intake, metadata=metadata,
                    preferences={'verified_gps_venues': [venue]}, fallback_defaults=fallback_defaults)
            if proposal:
                proposals.append(proposal)
        return proposals[0] if len(proposals) == 1 else {}
    raw_header = _source_header_text(text)
    header = _normalized(raw_header)
    mp_headings = {_normalized(venue['city']): proof for venue in venues
                   if venue['service_entity_type'] == 'ministerio_publico'
                   and (proof := _corroborated_mp_heading(raw_header, venue['city']))}
    source_kinds = {kind for kind, phrases in _AGENCIES.items() if any(_contains(header, phrase) for phrase in phrases)}
    if mp_headings:
        source_kinds.add('ministerio_publico')
    named_kind = _entity_kind(str(intake.get('service_entity') or ''))
    kind = intake.get('service_entity_type') or named_kind
    untouched_fallback = bool(mp_headings and source_kinds == {'ministerio_publico'}
        and profile.get('mode') == 'auto_fallback' and isinstance(fallback_defaults, dict)
        and kind in {'', 'court', 'other', None} and named_kind not in {'gnr', 'psp', 'police'}
        and all(str(intake.get(field) or '') == str(fallback_defaults.get(field) or '')
                for field in ('service_entity', 'service_entity_type'))
        and not any(fields.get(field) for field in ('service_entity', 'service_entity_type')))
    if untouched_fallback:
        kind = 'ministerio_publico'
    if (kind == 'court' and profile.get('mode') == 'auto_fallback'
            and intake.get('service_entity') and named_kind in _AGENCIES and source_kinds == {named_kind}):
        # Generic fallback profiles can retain a court type after OCR names the
        # agency. Only its own matching name and heading may correct that type.
        kind = named_kind
    if not isinstance(kind, str) or kind not in _AGENCIES or source_kinds != {kind}:
        return {}
    corroborated_entity = bool(kind == 'ministerio_publico' and intake.get('service_entity')
        and any(_normalized(str(intake['service_entity'])) == _normalized(proof['raw_excerpts'][0])
                for proof in mp_headings.values()))
    if (intake.get('service_entity') and named_kind not in {kind, 'other', ''}
            and not untouched_fallback and not corroborated_entity):
        return {}
    if kind == 'ministerio_publico' and re.search(
            r'\b(?:gnr|psp|pj|judiciaria|nacional republicana|seguranca publica)\b', header):
        return {}
    # A court heading quoting police/MP material is not an agency venue source.
    agency_starts = [header.find(phrase) for phrase in _AGENCIES[kind] if _contains(header, phrase)]
    if kind == 'ministerio_publico' and mp_headings:
        agency_starts.extend(header.find(_normalized(proof['raw_excerpts'][0])) for proof in mp_headings.values())
    agency_start = min(agency_starts)
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
        corroboration = (mp_headings.get(_normalized(venue['city']), {})
                         if kind == 'ministerio_publico' and not _contains(header, 'ministerio publico') else {})
        literal_phrases = [phrase for phrase in venue['required_source_phrases'] if _contains(header, phrase)]
        missing = set(venue['required_source_phrases']) - set(literal_phrases)
        if (venue['service_entity_type'] != kind or any(city != _normalized(venue['city']) for city in cities)
                or (missing and not (corroboration and missing <= {'ministerio publico'}))):
            continue
        distance = _distance_m(gps['latitude'], gps['longitude'], venue)
        if distance <= venue['radius_m']:
            matches.append((venue, round(distance, 2), literal_phrases, corroboration))
    if len(matches) != 1:
        return {}
    venue, distance, literal_phrases, corroboration = matches[0]
    reason = ('Editable venue default inferred from the specific source heading and nearby original photo GPS. ')
    if venue.get('geometry_basis') == 'user_confirmed_photo_venue':
        reason = ('Editable venue default from the specific source heading and a user-confirmed photo location. '
                  'Cited sources support the postal address; the point is not a surveyed building footprint. ')
    if corroboration:
        reason += ('The MP agency is corroborated from the two issuer-heading excerpts, '
                   'not printed in full as Ministério Público. ')
    reason += 'This is not a printed venue or proof of attendance or interpreting.'
    return {key: venue[key] for key in ('service_place', 'service_entity', 'service_entity_type')} | {
        'entities_differ': kind not in {'court', 'ministerio_publico'},
        'source_location_evidence': {
            'source': 'verified_gps_source_venue', 'source_sha256': intake['source_sha256'],
            'source_text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'source_agency_type': kind,
            'service_entity': venue['service_entity'], 'service_entity_type': kind,
            'venue_id': venue['id'], 'city': venue['city'], 'service_place': venue['service_place'],
            'distance_m': distance, 'radius_m': venue['radius_m'],
            'source_urls': list(venue['source_urls']), 'matched_source_phrases': literal_phrases,
            **{key: venue[key] for key in ('geometry_basis', 'confirmation_source_sha256', 'confirmation_date') if key in venue},
            **({'source_agency_corroboration': corroboration} if corroboration else {}),
            'editable': True,
            'reason': reason,
        },
    }
