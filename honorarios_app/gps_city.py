"""Optional city evidence from bounded, locally verified areas; never geocodes."""
from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlsplit

from scripts.entity_rules import normalize_text

MAX_VERIFIED_AREAS = 100
MAX_RADIUS_M = 500
EARTH_RADIUS_M = 6_371_008.8


def _number(value: Any, minimum: float, maximum: float) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and minimum <= value <= maximum and math.isfinite(value))


def _area(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    city = value.get('city')
    url = value.get('source_url')
    if (not isinstance(city, str) or not city.strip() or len(city) > 120
            or not any(char.isalpha() for char in city) or any(ord(char) < 32 for char in city)
            or not isinstance(url, str) or len(url) > 2000 or any(char.isspace() or ord(char) < 32 for char in url)):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            return None
    except ValueError:
        return None
    if (not _number(value.get('latitude'), -90, 90) or not _number(value.get('longitude'), -180, 180)
            or not _number(value.get('radius_m'), 0, MAX_RADIUS_M) or value['radius_m'] == 0):
        return None
    return {key: value[key] for key in ('latitude', 'longitude', 'radius_m', 'source_url')} | {'city': ' '.join(city.split())}


def _distance_m(latitude: float, longitude: float, area: dict[str, Any]) -> float:
    lat1, lat2 = math.radians(latitude), math.radians(area['latitude'])
    dlat = lat2 - lat1
    dlon = math.radians(area['longitude'] - longitude)
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))


def match_verified_gps_city(metadata: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    """Resolve only a single city inside explicitly configured verified circles.

    The catalog is user-managed evidence, not a nearest-place database. Any bad
    enabled entry invalidates the whole catalog. Original metadata is untouched;
    the caller must reconcile this derived city with embedded/visible/AI evidence.
    """
    catalog = preferences.get('verified_gps_areas', [])
    if catalog == []:
        return {'status': 'disabled'}
    if not isinstance(catalog, list) or len(catalog) > MAX_VERIFIED_AREAS:
        return {'status': 'invalid_configuration'}
    areas = [_area(item) for item in catalog]
    if any(area is None for area in areas):
        return {'status': 'invalid_configuration'}
    gps = metadata.get('gps_coordinates')
    if gps is None:
        return {'status': 'missing_gps'}
    if (not isinstance(gps, dict) or gps.get('source') != 'exif_gps'
            or not _number(gps.get('latitude'), -90, 90) or not _number(gps.get('longitude'), -180, 180)):
        return {'status': 'invalid_gps'}
    matches = []
    for area in areas:
        distance = _distance_m(gps['latitude'], gps['longitude'], area)
        if distance <= area['radius_m']:
            matches.append({**area, 'distance_m': round(distance, 2)})
    if not matches:
        return {'status': 'outside_verified_areas'}
    cities = {' '.join(normalize_text(area['city']).split()): area['city'] for area in matches}
    result = {'status': 'matched' if len(cities) == 1 else 'ambiguous',
              'source': 'verified_gps_area', 'matches': matches}
    if len(cities) == 1:
        result['city'] = next(iter(cities.values()))
    return result
