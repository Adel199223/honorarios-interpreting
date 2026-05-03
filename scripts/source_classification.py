from __future__ import annotations

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
    r"documento\s+traduzido",
    r"numero\s+de\s+palavras",
    r"n[uú]mero\s+de\s+palavras",
    r"\bpalavras\b",
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


def detect_translation_source(intake: dict[str, Any]) -> list[str]:
    normalized = normalize_text(source_text_for_classification(intake))
    matches: list[str] = []
    for pattern in TRANSLATION_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            matches.append(pattern)
    return matches


def format_translation_rejection(matches: list[str]) -> str:
    joined = ", ".join(matches)
    return (
        "This looks like a translation or word-count honorários request, "
        f"not an in-person interpreting request. Matched: {joined}"
    )
