from __future__ import annotations

import copy
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.generate_pdf import IntakeError


DEFAULT_PRIMARY_PROFILE_ID = "primary"
PROFILE_STORE_SCHEMA_VERSION = 1
LEGALPDF_SETTINGS_PATH = Path.home() / "AppData" / "Roaming" / "LegalPDFTranslate" / "settings.json"
LEGALPDF_PROFILE_IMPORT_CONFIRMATION_PHRASE = "COPY LEGALPDF PROFILES"

DEFAULT_PROFILE_DISTANCES = {
    "Beja": 39,
    "Moura": 26,
    "Vidigueira": 15,
    "Cuba": 25,
    "Odemira": 132,
    "Ferreira do Alentejo": 50,
    "Serpa": 34,
    "Brinches": 23,
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def create_profile_id(first_name: str, last_name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{first_name}-{last_name}".casefold()).strip("-")
    return base or f"profile-{secrets.token_hex(4)}"


def normalize_distance_label(label: Any) -> str:
    return _text(label)


def normalize_travel_distances(value: Any) -> dict[str, int]:
    distances: dict[str, int] = {}
    if isinstance(value, dict):
        iterable = value.items()
    elif isinstance(value, list):
        iterable = []
        for item in value:
            if isinstance(item, dict):
                label = item.get("city") or item.get("destination") or item.get("label")
                km = item.get("km_one_way") or item.get("km")
                iterable.append((label, km))
    else:
        iterable = []
    for raw_label, raw_km in iterable:
        label = normalize_distance_label(raw_label)
        if not label:
            continue
        try:
            km = int(float(str(raw_km).replace(",", ".")))
        except (TypeError, ValueError):
            continue
        if km < 0:
            continue
        distances[label] = km
    return distances


def profile_display_name(profile: dict[str, Any]) -> str:
    override = _text(profile.get("document_name_override"))
    if override:
        return override
    name = f"{_text(profile.get('first_name'))} {_text(profile.get('last_name'))}".strip()
    return name or _text(profile.get("id")) or "Profile"


def profile_from_mapping(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    first_name = _text(source.get("first_name"))
    last_name = _text(source.get("last_name"))
    profile_id = _text(source.get("id")) or create_profile_id(first_name, last_name)
    profile = {
        "id": profile_id,
        "first_name": first_name,
        "last_name": last_name,
        "document_name_override": _text(source.get("document_name_override") or source.get("document_name")),
        "email": _text(source.get("email")),
        "phone_number": _text(source.get("phone_number") or source.get("phone")),
        "postal_address": _text(source.get("postal_address") or source.get("address")),
        "iban": _text(source.get("iban")),
        "iva_text": _text(source.get("iva_text") or source.get("vat_text") or "23%"),
        "irs_text": _text(source.get("irs_text") or "Sem retenção"),
        "travel_origin_label": _text(source.get("travel_origin_label") or source.get("default_origin") or "Marmelar"),
        "travel_distances_by_city": normalize_travel_distances(source.get("travel_distances_by_city") or source.get("distances")),
    }
    return profile


def split_name(name: str) -> tuple[str, str]:
    parts = _text(name).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def synthesize_profile_from_legacy(legacy_profile: dict[str, Any] | None, known_destinations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    legacy = legacy_profile if isinstance(legacy_profile, dict) else {}
    applicant_name = _text(legacy.get("applicant_name") or legacy.get("signature_name"))
    first_name, last_name = split_name(applicant_name)
    distances = dict(DEFAULT_PROFILE_DISTANCES)
    for item in known_destinations or []:
        if not isinstance(item, dict):
            continue
        label = _text(item.get("destination") or item.get("name") or item.get("city"))
        if not label:
            continue
        try:
            distances[label] = int(float(str(item.get("km_one_way") or item.get("km") or "")))
        except (TypeError, ValueError):
            continue
    return {
        "id": DEFAULT_PRIMARY_PROFILE_ID,
        "first_name": first_name,
        "last_name": last_name,
        "document_name_override": applicant_name,
        "email": "",
        "phone_number": "",
        "postal_address": _text(legacy.get("address")),
        "iban": _text(legacy.get("iban")),
        "iva_text": _extract_iva_text(_text(legacy.get("vat_irs_phrase"))),
        "irs_text": _extract_irs_text(_text(legacy.get("vat_irs_phrase"))),
        "travel_origin_label": _text(legacy.get("default_origin") or "Marmelar"),
        "travel_distances_by_city": distances,
    }


def blank_profile() -> dict[str, Any]:
    return {
        "id": f"profile-{secrets.token_hex(4)}",
        "first_name": "",
        "last_name": "",
        "document_name_override": "",
        "email": "",
        "phone_number": "",
        "postal_address": "",
        "iban": "",
        "iva_text": "23%",
        "irs_text": "Sem retenção",
        "travel_origin_label": "Marmelar",
        "travel_distances_by_city": {},
    }


def normalize_profile_store(data: Any, *, fallback_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    source = data if isinstance(data, dict) else {}
    raw_profiles = source.get("profiles")
    profiles: list[dict[str, Any]] = []
    if isinstance(raw_profiles, list):
        profiles = [profile_from_mapping(item) for item in raw_profiles if isinstance(item, dict)]
    elif isinstance(raw_profiles, dict):
        profiles = [profile_from_mapping({"id": key, **item}) for key, item in raw_profiles.items() if isinstance(item, dict)]

    if not profiles and fallback_profile:
        profiles = [profile_from_mapping(fallback_profile)]
    if not profiles:
        profiles = [profile_from_mapping(blank_profile())]

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for profile in profiles:
        profile_id = _text(profile.get("id")) or create_profile_id(profile.get("first_name", ""), profile.get("last_name", ""))
        candidate = profile_id
        counter = 2
        while candidate in seen:
            candidate = f"{profile_id}-{counter}"
            counter += 1
        profile["id"] = candidate
        seen.add(candidate)
        unique.append(profile)

    primary_id = _text(source.get("primary_profile_id"))
    if primary_id not in seen:
        primary_id = unique[0]["id"]
    return {
        "schema_version": PROFILE_STORE_SCHEMA_VERSION,
        "primary_profile_id": primary_id,
        "profiles": unique,
    }


def load_json_if_exists(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default)


def load_profile_store(
    profile_store_path: Path,
    legacy_profile_path: Path,
    known_destinations_path: Path | None = None,
) -> dict[str, Any]:
    known_destinations = load_json_if_exists(known_destinations_path, []) if known_destinations_path else []
    legacy_profile = load_json_if_exists(legacy_profile_path, {})
    fallback = synthesize_profile_from_legacy(legacy_profile, known_destinations if isinstance(known_destinations, list) else [])
    if profile_store_path.exists():
        return normalize_profile_store(load_json_if_exists(profile_store_path, {}), fallback_profile=fallback)
    return normalize_profile_store({"primary_profile_id": DEFAULT_PRIMARY_PROFILE_ID, "profiles": [fallback]}, fallback_profile=fallback)


def main_profile(store: dict[str, Any]) -> dict[str, Any]:
    primary_id = _text(store.get("primary_profile_id"))
    profiles = store.get("profiles") if isinstance(store.get("profiles"), list) else []
    for profile in profiles:
        if isinstance(profile, dict) and _text(profile.get("id")) == primary_id:
            return profile
    if profiles and isinstance(profiles[0], dict):
        return profiles[0]
    raise IntakeError("No personal profile is available.")


def find_profile(store: dict[str, Any], profile_id: str | None) -> dict[str, Any]:
    target = _text(profile_id)
    if not target:
        return main_profile(store)
    for profile in store.get("profiles") or []:
        if isinstance(profile, dict) and _text(profile.get("id")) == target:
            return profile
    raise IntakeError(f"Unknown personal profile: {target}")


def _extract_iva_text(phrase: str) -> str:
    match = re.search(r"IVA\s+de\s+([0-9]+%?)", phrase, re.IGNORECASE)
    if match:
        return match.group(1)
    return "23%"


def _extract_irs_text(phrase: str) -> str:
    if "não está sujeito" in phrase.casefold() or "nao esta sujeito" in phrase.casefold() or "sem reten" in phrase.casefold():
        return "Sem retenção"
    return "Sem retenção"


def vat_irs_phrase(profile: dict[str, Any], legacy_defaults: dict[str, Any] | None = None) -> str:
    iva = _text(profile.get("iva_text") or "23%")
    irs = _text(profile.get("irs_text") or "Sem retenção")
    if "iva" in iva.casefold() and ("irs" in iva.casefold() or "reten" in iva.casefold()):
        return iva
    if "sem reten" in irs.casefold() or "não está sujeito" in irs.casefold() or "nao esta sujeito" in irs.casefold():
        return f"Este serviço inclui a taxa de IVA de {iva} e não está sujeito a retenção de IRS."
    if legacy_defaults and _text(legacy_defaults.get("vat_irs_phrase")):
        return _text(legacy_defaults.get("vat_irs_phrase"))
    return f"Este serviço inclui a taxa de IVA de {iva} e {irs}."


def profile_to_generator_profile(profile: dict[str, Any], legacy_defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    legacy = legacy_defaults if isinstance(legacy_defaults, dict) else {}
    display_name = profile_display_name(profile)
    return {
        "applicant_name": display_name,
        "address": _text(profile.get("postal_address")),
        "default_origin": _text(profile.get("travel_origin_label") or legacy.get("default_origin") or "Marmelar"),
        "iban": _text(profile.get("iban")),
        "vat_irs_phrase": vat_irs_phrase(profile, legacy),
        "payment_phrase": _text(legacy.get("payment_phrase") or "O pagamento deverá ser efetuado para o seguinte IBAN:"),
        "default_closing_city": _text(legacy.get("default_closing_city") or profile.get("travel_origin_label") or "Beja"),
        "default_closing_phrase": _text(legacy.get("default_closing_phrase") or "Pede deferimento,"),
        "signature_label": _text(legacy.get("signature_label") or "O Requerente,"),
        "signature_name": display_name,
    }


def missing_required_fields(profile: dict[str, Any]) -> list[str]:
    required = ["first_name", "last_name", "postal_address", "iban", "iva_text", "irs_text", "travel_origin_label"]
    return [key for key in required if not _text(profile.get(key))]


def validate_profile(profile: dict[str, Any]) -> None:
    missing = missing_required_fields(profile)
    if missing:
        raise IntakeError(f"Personal profile is missing required field(s): {', '.join(missing)}")


def save_profile_store(
    profile_store_path: Path,
    legacy_profile_path: Path,
    store: dict[str, Any],
    *,
    legacy_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_profile_store(store)
    for profile in normalized["profiles"]:
        validate_profile(profile)
    profile_store_path.parent.mkdir(parents=True, exist_ok=True)
    profile_store_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    selected = main_profile(normalized)
    legacy_profile_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_profile_path.write_text(
        json.dumps(profile_to_generator_profile(selected, legacy_defaults), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return normalized


def profile_summary(store: dict[str, Any]) -> dict[str, Any]:
    primary = main_profile(store)
    return {
        "schema_version": PROFILE_STORE_SCHEMA_VERSION,
        "primary_profile_id": store.get("primary_profile_id"),
        "profile_count": len(store.get("profiles") or []),
        "profiles": store.get("profiles") or [],
        "main_profile": primary,
        "main_profile_display_name": profile_display_name(primary),
        "travel_origin": _text(primary.get("travel_origin_label")),
        "distance_count": len(primary.get("travel_distances_by_city") or {}),
        "send_allowed": False,
    }


def lookup_profile_distance(profile: dict[str, Any], destination: str) -> tuple[int | None, str]:
    query = _text(destination)
    if not query:
        return None, ""
    distances = profile.get("travel_distances_by_city") if isinstance(profile.get("travel_distances_by_city"), dict) else {}
    query_fold = query.casefold()
    for label, km in distances.items():
        label_text = _text(label)
        if not label_text:
            continue
        label_fold = label_text.casefold()
        if query_fold == label_fold or query_fold in label_fold or label_fold in query_fold:
            try:
                return int(km), label_text
            except (TypeError, ValueError):
                return None, ""
    return None, ""


def apply_profile_defaults_to_intake(intake: dict[str, Any], profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    effective = copy.deepcopy(intake)
    transport = effective.get("transport") if isinstance(effective.get("transport"), dict) else {}
    transport = copy.deepcopy(transport)
    provenance: dict[str, Any] = {
        "personal_profile_id": _text(profile.get("id")),
        "personal_profile_name": profile_display_name(profile),
        "applied": [],
        "distance_source": "",
    }
    if _text(profile.get("id")):
        effective.setdefault("personal_profile_id", _text(profile.get("id")))
    if not _text(transport.get("origin")):
        origin = _text(profile.get("travel_origin_label"))
        if origin:
            transport["origin"] = origin
            provenance["applied"].append("transport.origin")
    has_transport = bool(effective.get("claim_transport", True)) or bool(transport)
    if has_transport and not _text(transport.get("km_one_way")):
        destination = _text(transport.get("destination") or effective.get("transport_destination") or effective.get("service_place"))
        km, label = lookup_profile_distance(profile, destination)
        if km is not None:
            transport["km_one_way"] = km
            if not _text(transport.get("destination")):
                transport["destination"] = label or destination
                provenance["applied"].append("transport.destination")
            provenance["applied"].append("transport.km_one_way")
            provenance["distance_source"] = f"personal_profile:{label or destination}"
    if transport:
        effective["transport"] = transport
    return effective, provenance


def legalpdf_settings_path_from_payload(payload: dict[str, Any] | None = None) -> Path:
    raw = _text((payload or {}).get("settings_path"))
    return Path(raw).expanduser() if raw else LEGALPDF_SETTINGS_PATH


def load_legalpdf_profiles(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    settings_json = _text((payload or {}).get("settings_json"))
    if settings_json:
        try:
            settings = json.loads(settings_json)
        except json.JSONDecodeError as exc:
            raise IntakeError(f"LegalPDF settings JSON is invalid: {exc}") from exc
    else:
        settings_path = legalpdf_settings_path_from_payload(payload)
        if not settings_path.exists():
            raise IntakeError(f"LegalPDF settings file was not found: {settings_path}")
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntakeError("LegalPDF settings file could not be read.") from exc
    candidate = settings
    if isinstance(settings, dict):
        normalized_payload = settings.get("normalized_payload")
        if isinstance(normalized_payload, dict):
            profile_summary_data = normalized_payload.get("profile_summary")
            if isinstance(profile_summary_data, dict):
                candidate = profile_summary_data
            elif isinstance(normalized_payload.get("profiles"), list):
                candidate = normalized_payload
        elif isinstance(settings.get("profile_summary"), dict):
            candidate = settings["profile_summary"]
        elif isinstance(settings.get("settings"), dict) and isinstance(settings["settings"].get("profiles"), list):
            candidate = settings["settings"]
    return normalize_profile_store(candidate)


def merge_profile_stores(current: dict[str, Any], incoming: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    current_store = normalize_profile_store(current)
    incoming_store = normalize_profile_store(incoming)
    by_id = {profile["id"]: copy.deepcopy(profile) for profile in current_store["profiles"]}
    changes: list[dict[str, Any]] = []
    for incoming_profile in incoming_store["profiles"]:
        profile_id = incoming_profile["id"]
        before = by_id.get(profile_id)
        by_id[profile_id] = copy.deepcopy(incoming_profile)
        action = "update" if before else "create"
        changed = json.dumps(before, ensure_ascii=False, sort_keys=True) != json.dumps(incoming_profile, ensure_ascii=False, sort_keys=True)
        changes.append({
            "profile_id": profile_id,
            "display_name": profile_display_name(incoming_profile),
            "action": action if changed else "unchanged",
        })
    order = [profile["id"] for profile in current_store["profiles"] if profile["id"] in by_id]
    for profile in incoming_store["profiles"]:
        if profile["id"] not in order:
            order.append(profile["id"])
    primary_id = incoming_store.get("primary_profile_id") or current_store.get("primary_profile_id")
    merged = {
        "schema_version": PROFILE_STORE_SCHEMA_VERSION,
        "primary_profile_id": primary_id if primary_id in by_id else (order[0] if order else DEFAULT_PRIMARY_PROFILE_ID),
        "profiles": [by_id[profile_id] for profile_id in order],
    }
    return normalize_profile_store(merged), changes


def personal_profile_import_report(changes: list[dict[str, Any]], reason: str, backup_file: str) -> dict[str, Any]:
    return {
        "kind": "legalpdf_personal_profile_import_report",
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "imported",
        "import_reason": reason,
        "changes": changes,
        "pre_import_backup_file": backup_file,
        "legalpdf_write_allowed": False,
        "send_allowed": False,
    }
