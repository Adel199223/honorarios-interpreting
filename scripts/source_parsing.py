"""Conservative source-role parsing shared by recovery and review helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

try:
    from scripts.entity_rules import normalize_text
except ModuleNotFoundError:
    from entity_rules import normalize_text


DATE_RE = re.compile(r"\b(?:(20\d{2})-(\d{2})-(\d{2})|(\d{1,2})/(\d{1,2})/(20\d{2}))\b")
SERVICE_DATE_RE = re.compile(
    r"\b(?:servico(?: de interpretacao)?|interpretacao|diligencia|audiencia|"
    r"service date|interpreting service|provided|prestou|compareceu|"
    r"prestad[oa]|realizad[oa]|efetuad[oa]|decorreu|ocorreu)\b"
)
OTHER_DATE_RE = re.compile(
    r"\b(?:emitid[oa]|emissao|expedid[oa]|assinad[oa]|enviad[oa]|"
    r"data (?:do documento|da notificacao|de fecho)|assinatura|pede deferimento|closing date|issued|"
    r"agendad[oa]|marcad[oa]|designad[oa]|convocad[oa]|comparecer|"
    r"scheduled|appointment|captura|metadados|metadata|fotografia|photo)\b"
)
PLACE_ANCHOR_RE = re.compile(
    r"\b(?:local(?: da diligencia| do servico| de realizacao)?\s*:|"
    r"servico(?: de interpretacao)?|interpretacao|diligencia|audiencia|"
    r"prestad[oa]|realizad[oa]|efetuad[oa]|decorreu|ocorreu|compareceu\b)"
)
PLACE_PREPOSITION_RE = re.compile(r"\b(?:no|na|nos|nas|em)\s+(?=[a-z])")
PLACE_END_RE = re.compile(
    r",|\b(?:no dia|em\s+(?:20\d{2}-|\d{1,2}/)|as\s+\d|"
    r"no ambito|processo|nuipc|para\s+|e\s+(?:no|na|em)\s+)"
)


@dataclass(frozen=True)
class ServiceDateEvidence:
    value: str = ""
    candidates: tuple[str, ...] = ()
    warning: str = ""

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.candidates and not self.value)


def _date_role(text: str, start: int, end: int) -> str:
    # Limit labels to this clause, so a document header cannot label a later
    # service date and a service paragraph cannot relabel an issue date.
    left_boundary = max((text.rfind(char, 0, start) for char in "\n;.!?"), default=-1) + 1
    right_positions = [position for char in "\n;.!?" if (position := text.find(char, end)) >= 0]
    right_boundary = min(right_positions, default=len(text))
    clause = text[left_boundary:right_boundary]
    relative_start = start - left_boundary
    relative_end = end - left_boundary
    labels: list[tuple[int, str]] = []
    for expression, role in ((SERVICE_DATE_RE, "service"), (OTHER_DATE_RE, "other")):
        for match in expression.finditer(clause):
            if match.end() <= relative_start:
                distance = relative_start - match.end()
            elif match.start() >= relative_end:
                distance = match.start() - relative_end + 25
            else:
                continue
            if distance <= 140:
                labels.append((distance, role))
    if not labels:
        return "unknown"
    return min(labels, key=lambda item: (item[0], item[1] != "other"))[1]


def service_date_evidence(text: str) -> ServiceDateEvidence:
    normalized = normalize_text(text or "")
    found: list[tuple[str, str]] = []
    for match in DATE_RE.finditer(normalized):
        iso_year, iso_month, iso_day, eu_day, eu_month, eu_year = match.groups()
        try:
            value = datetime(int(iso_year or eu_year), int(iso_month or eu_month), int(iso_day or eu_day)).date().isoformat()
        except ValueError:
            continue
        found.append((value, _date_role(normalized, match.start(), match.end())))
    candidates = tuple(dict.fromkeys(value for value, _role in found))
    service_dates = tuple(dict.fromkeys(value for value, role in found if role == "service"))
    if len(service_dates) == 1:
        return ServiceDateEvidence(value=service_dates[0], candidates=candidates)
    if len(service_dates) > 1:
        return ServiceDateEvidence(candidates=candidates, warning="Several service dates appear in the source. Confirm the date of the interpreting service before PDF creation.")
    if len(candidates) == 1 and any(role == "unknown" for _value, role in found):
        # Preserve the single unlabelled-date case; explicit issue, appointment
        # and capture labels never supply the service date by themselves.
        return ServiceDateEvidence(value=candidates[0], candidates=candidates)
    if candidates:
        warning = (
            "The source contains several dates without one clear service date. Confirm the date of the interpreting service before PDF creation."
            if len(candidates) > 1 else
            "The source date is labelled as document, appointment or capture metadata. Confirm the date of the interpreting service before PDF creation."
        )
        return ServiceDateEvidence(candidates=candidates, warning=warning)
    return ServiceDateEvidence()


def _place_tail(raw_text: str) -> str:
    normalized = normalize_text(raw_text)
    boundary = PLACE_END_RE.search(normalized)
    return raw_text[:boundary.start() if boundary else len(raw_text)].strip(" :,-")


def explicit_service_places(text: str) -> tuple[str, ...]:
    """Return only locations connected to a service/local label, not headers."""
    places: list[str] = []
    for clause in re.split(r"[\n;.!?]", text or ""):
        normalized = normalize_text(clause)
        anchors = list(PLACE_ANCHOR_RE.finditer(normalized))
        if not anchors:
            continue
        for anchor in anchors:
            if anchor.group().rstrip().endswith(":"):
                place = _place_tail(clause[anchor.end():])
                if place:
                    places.append(place)
                continue
            for match in PLACE_PREPOSITION_RE.finditer(normalized, anchor.end()):
                # An issuer's office mentioned before this anchor is excluded.
                place = _place_tail(clause[match.end():])
                if place and len(place) >= 3 and not re.match(r"(?:diligencia|audiencia|interpretacao|servico|lingua|portugues|ingles|arabe)\b", normalize_text(place)):
                    places.append(place)
    unique: dict[str, str] = {}
    for place in places:
        unique.setdefault(normalize_text(place).strip(), place)
    return tuple(unique.values())
