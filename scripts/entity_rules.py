from __future__ import annotations

import re
from typing import Any


ENTITY_TYPES = {"court", "ministerio_publico", "gnr", "psp", "police", "other"}
PJ_CONTEXT_RE = re.compile(r"policia judiciaria|\bpj\b|\bdiretoria\b|\binspetor(?:a)?\b")
HOST_BUILDING_RE = re.compile(
    r"\bposto\b|\bgnr\b|guarda nacional republicana|\besquadra\b|\btribunal\b|"
    r"\bministerio publico\b|\bedificio\b|\binstalac(?:ao|oes)\b|\bunidade\b|"
    r"\bhospital\b|\bgabinete\b|\binstituto\b|medico legal|medico-legal"
)
HOST_LOCALITY_RE = re.compile(
    r"(?:\bde\b|\bem\b|\bno\b|\bna\b|\s-)\s+"
    r"(beja|ferreira do alentejo|cuba|moura|serpa|beringel|pedrogao|pedrago|vidigueira)\b"
)
NON_COURT_PLACE_CLUE_RE = re.compile(
    r"\bposto\b|\besquadra\b|\bdestacamento\b|\bhospital\b|\bgabinete\b|"
    r"\binstituto\b|\bgnr\b|\bpsp\b|guarda nacional republicana|\bpolicia\b"
)


def normalize_text(value: str) -> str:
    replacements = str.maketrans(
        {
            "á": "a",
            "à": "a",
            "â": "a",
            "ã": "a",
            "é": "e",
            "ê": "e",
            "í": "i",
            "ó": "o",
            "ô": "o",
            "õ": "o",
            "ú": "u",
            "ç": "c",
            "Á": "a",
            "À": "a",
            "Â": "a",
            "Ã": "a",
            "É": "e",
            "Ê": "e",
            "Í": "i",
            "Ó": "o",
            "Ô": "o",
            "Õ": "o",
            "Ú": "u",
            "Ç": "c",
        }
    )
    return value.translate(replacements).lower()


def classify_entity_type(value: str) -> str:
    normalized = normalize_text(value)
    if re.search(r"\bgnr\b|guarda nacional republicana|posto territorial", normalized):
        return "gnr"
    if re.search(r"\bpsp\b|policia de seguranca publica|esquadra", normalized):
        return "psp"
    if re.search(r"\bpolicia\b|police", normalized):
        return "police"
    if re.search(r"ministerio publico|procurador|procuradora", normalized):
        return "ministerio_publico"
    if re.search(r"\btribunal\b|comarca|juizo|juizo", normalized):
        return "court"
    return "other"


def is_non_court_service_type(entity_type: str) -> bool:
    return entity_type in {"gnr", "psp", "police", "other"}


def source_mentions_non_court_service(intake: dict[str, Any]) -> bool:
    text = "\n".join(
        str(intake.get(key) or "")
        for key in ("source_text", "notes", "service_entity", "service_place", "service_place_phrase")
    )
    normalized = normalize_text(text)
    return classify_entity_type(normalized) in {"gnr", "psp", "police"} or bool(NON_COURT_PLACE_CLUE_RE.search(normalized))


def source_mentions_pj_context(intake: dict[str, Any]) -> bool:
    text = "\n".join(
        str(intake.get(key) or "")
        for key in ("source_text", "notes", "service_entity", "service_place", "service_place_phrase")
    )
    return bool(PJ_CONTEXT_RE.search(normalize_text(text)))


def has_pj_host_building(intake: dict[str, Any]) -> bool:
    if not source_mentions_pj_context(intake):
        return True

    candidates = [
        str(intake.get("service_place") or ""),
        str(intake.get("service_place_phrase") or ""),
    ]
    for candidate in candidates:
        normalized = normalize_text(candidate).strip()
        if not normalized:
            continue
        if not HOST_BUILDING_RE.search(normalized):
            continue
        if not HOST_LOCALITY_RE.search(normalized):
            continue
        if re.fullmatch(r"(policia judiciaria|pj|diretoria(?: do sul)?)", normalized):
            continue
        return True
    return False


def infer_payment_entity(intake: dict[str, Any]) -> str:
    explicit = str(intake.get("payment_entity") or "").strip()
    if explicit:
        return explicit
    addressee = str(intake.get("addressee") or "").strip()
    if addressee:
        return addressee
    return ""


def infer_service_entity(intake: dict[str, Any], payment_entity: str) -> str:
    explicit = str(intake.get("service_entity") or "").strip()
    if explicit:
        return explicit
    legacy_place = str(intake.get("service_place") or "").strip()
    if legacy_place:
        return legacy_place
    if payment_entity and classify_entity_type(payment_entity) in {"court", "ministerio_publico"}:
        return payment_entity
    return ""


def infer_service_entity_type(intake: dict[str, Any], service_entity: str) -> str:
    explicit = str(intake.get("service_entity_type") or "").strip().lower()
    if explicit:
        if explicit not in ENTITY_TYPES:
            return "other"
        return explicit
    return classify_entity_type(service_entity)


def infer_entities_differ(intake: dict[str, Any], payment_entity: str, service_entity: str, service_entity_type: str) -> bool:
    if "entities_differ" in intake:
        return bool(intake["entities_differ"])
    payment_key = normalize_text(payment_entity).strip()
    service_key = normalize_text(service_entity).strip()
    if not payment_key or not service_key:
        return False
    if payment_key == service_key:
        return False
    return is_non_court_service_type(service_entity_type)


def resolve_entities(intake: dict[str, Any]) -> dict[str, Any]:
    payment_entity = infer_payment_entity(intake)
    service_entity = infer_service_entity(intake, payment_entity)
    service_entity_type = infer_service_entity_type(intake, service_entity)
    entities_differ = infer_entities_differ(intake, payment_entity, service_entity, service_entity_type)
    return {
        "payment_entity": payment_entity,
        "service_entity": service_entity,
        "service_entity_type": service_entity_type,
        "entities_differ": entities_differ,
    }


def build_service_place_clause(intake: dict[str, Any], service_entity: str) -> str:
    explicit_phrase = str(intake.get("service_place_phrase") or "").strip()
    if explicit_phrase:
        return explicit_phrase

    normalized = normalize_text(service_entity).strip()
    if normalized.startswith(("em ", "no ", "na ", "nos ", "nas ")):
        return service_entity
    if normalized.startswith("esquadra"):
        return f"na {service_entity}"
    if normalized.startswith(("posto", "tribunal", "ministerio publico")):
        return f"no {service_entity}"
    if normalized.startswith(("gnr", "psp")):
        return f"na {service_entity}"
    return f"em {service_entity}"
