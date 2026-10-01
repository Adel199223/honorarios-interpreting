from __future__ import annotations

import hashlib
import re
from typing import Any

try:
    from scripts.entity_rules import normalize_text
except ModuleNotFoundError:
    from entity_rules import normalize_text


TRANSLATION_PATTERNS = [
    r"\btradutor(?:a)?\b",
    r"\btraducao\b",
    r"\btraducoes\b",
    r"\btraduzir\b",
    r"documento\s+traduzido",
    r"numero\s+de\s+palavras",
    r"n[uú]mero\s+de\s+palavras",
    r"\b\d+(?:[.,]\d+)?\s+palavras\b",
    r"\b(?:contagem|total|quantidade)\s+(?:de\s+)?palavras\b",
]


def source_text_for_classification(intake: dict[str, Any]) -> str:
    parts = [
        str(intake.get(key, ""))
        for key in ("source_text", "service_place", "notes", "source_filename")
    ]
    ai_recovery = intake.get("ai_recovery")
    if isinstance(ai_recovery, dict):
        parts.append(str(ai_recovery.get("raw_visible_text") or ""))
        indicators = ai_recovery.get("translation_indicators")
        if isinstance(indicators, list):
            parts.extend(str(item) for item in indicators)
    return "\n".join(parts)


def translation_indicators(intake: dict[str, Any]) -> list[str]:
    normalized = normalize_text(source_text_for_classification(intake))
    matches: list[str] = []
    for pattern in TRANSLATION_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            matches.append(pattern)
    return matches


INTERPRETING_RE = re.compile(r'\b(?:interprete|interpretacao|interpreter|interpreting)\b')
APPOINTMENT_RE = re.compile(r'\b(?:comparecer|comparecimento|presenca|audiencia|diligencia|appointment|attend|hearing)\b')
ASSIGNMENT_RE = re.compile(r'\b(?:comparecer|comparecimento|presenca|attend|nomead[oa]|designad[oa]|convocad[oa]|appointed|assigned)\b')
DATE_RE = re.compile(r'\b(?:20\d{2}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]20\d{2}|\d{1,2}\s+de\s+(?:janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+20\d{2})\b')
UNCERTAIN_RE = re.compile(r'\b(?:nao|not|sem|eventual|eventualmente|caso|se necessario|if needed|may|podera|dispensad[oa]|cancelad[oa]|anulad[oa]|adiad[oa]|desmarcad[oa])\b')


def interpreting_source_text(intake: dict[str, Any]) -> str:
    """Only visible source evidence can establish an interpreting assignment."""
    ai = intake.get('ai_recovery') or {}
    parts = [str(intake.get('source_text') or ''), str(ai.get('raw_visible_text') or '') if isinstance(ai, dict) else '']
    return '\n'.join(dict.fromkeys(part.strip() for part in parts if part.strip()))


def source_scope_fingerprint(intake: dict[str, Any]) -> str:
    return hashlib.sha256(source_text_for_classification(intake).encode('utf-8')).hexdigest()


def explicit_interpreting_assignment(intake: dict[str, Any]) -> bool:
    text = normalize_text(interpreting_source_text(intake))
    # Inspect the interpreting clause, not a separate translation deadline.
    for clause in re.split(r'\n\s*\n|[;!?]|(?<=[a-z])\.\s+', text):
        if not INTERPRETING_RE.search(clause) or UNCERTAIN_RE.search(clause):
            continue
        if re.search(r'\b(?:servico de interpretacao|interpretacao presencial|interpreting service)\b', clause) and re.search(r'\b(?:realizad[oa]|prestad[oa]|prestou|provided|performed)\b', clause):
            return True
        if re.search(r'\b(?:traduzir|traducao escrita|written translation|documento traduzido)\b', clause) and not re.search(r'\b(?:comparecer|comparecimento|presenca|attend|interpretacao presencial)\b', clause):
            continue
        if APPOINTMENT_RE.search(clause) and ASSIGNMENT_RE.search(clause) and DATE_RE.search(clause):
            return True
    return False


def classify_source_work(intake: dict[str, Any]) -> str:
    if not translation_indicators(intake):
        return 'interpreting'
    visible = normalize_text(interpreting_source_text(intake))
    if not INTERPRETING_RE.search(visible):
        return 'translation'
    confirmation = intake.get('mixed_notice_scope') if intake.get('mixed_notice_scope_fingerprint') == source_scope_fingerprint(intake) else ''
    if confirmation == 'translation-only':
        return 'translation'
    if explicit_interpreting_assignment(intake) or confirmation == 'interpreting-only':
        return 'mixed_interpreting'
    return 'ambiguous_mixed'


def detect_translation_source(intake: dict[str, Any]) -> list[str]:
    return translation_indicators(intake) if classify_source_work(intake) == 'translation' else []


def format_translation_rejection(matches: list[str]) -> str:
    joined = ", ".join(matches)
    return (
        "This looks like a translation or word-count honorários request, "
        f"not an in-person interpreting request. Matched: {joined}"
    )
