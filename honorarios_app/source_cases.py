"""Separate visible case references without joining alternatives into one ID."""
from __future__ import annotations

import re
from typing import Any

from scripts.request_identity import normalize_case_number

CASE_FULL = re.compile(r'\d+/\d{2}\.\d[A-Z][A-Z0-9]*(?:\.[A-Z0-9]+)*', re.IGNORECASE)
CASE_VISIBLE = re.compile(r'(?<![A-Z0-9/])\d+\s*/\s*\d{2}\s*\.\s*\d\s*[A-Z][A-Z0-9]*(?:\.[A-Z0-9]+)*', re.IGNORECASE)
SPACED_SUFFIX_TAIL = re.compile(
    r'(?:[ \t]+[A-Za-z0-9](?=[ \t]|$|[.,;:!?)])){2,}'
    r'|[ \t]+[A-Z0-9](?=[ \t]|$|[.,;:!?)])'
)
GROUPED_SUFFIX_TAIL = re.compile(r'(?:[ \t]+[A-Z0-9]{2,4})+(?=$|[.,;:!?)])')
ALTERNATIVE = re.compile(r'\b(?:ou|or|ileg[ií]v\w*|unreadable|uncertain|ambiguous|incerto)\b|\?', re.IGNORECASE)


def valid_source_case(value: Any) -> str:
    normalized = normalize_case_number(str(value or ''))
    return normalized if CASE_FULL.fullmatch(normalized) else ''


def source_scope_requires_review(text: str, ai_recovery: dict[str, Any]) -> bool:
    """Never turn uncertain document/background membership into ready identities.

    Legacy recoveries have no scope key. New recoveries keep background OCR out
    of the relevant text; contradictory streams require review, not regex-based
    deletion of a possibly legitimate foreground case.
    """
    if ai_recovery.get('source_scope', 'clear') != 'clear':
        return True
    background = ai_recovery.get('incidental_background_text', '')
    if not isinstance(background, str):
        return True
    if not background.strip():
        return False
    foreground = str(text or '')
    if background.strip() in foreground:
        return True
    background_cases = {valid_source_case(match.group()) for match in CASE_VISIBLE.finditer(background)} - {''}
    foreground_cases = {valid_source_case(match.group()) for match in CASE_VISIBLE.finditer(foreground)} - {''}
    declared = ai_recovery.get('case_numbers')
    if isinstance(declared, list):
        foreground_cases.update(valid_source_case(value) for value in declared if isinstance(value, str))
    fields = ai_recovery.get('fields') or {}
    if isinstance(fields, dict):
        foreground_cases.update(valid_source_case(fields.get(key)) for key in ('case_number', 'raw_case_number'))
    return bool(background_cases & foreground_cases)


def source_case_rows(text: str, ai_recovery: dict[str, Any]) -> list[dict[str, str]]:
    """Keep readable rows and unresolved alternatives, including legacy OCR."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    ambiguous_cases: set[str] = set()
    fragmented_cases: set[str] = set()
    non_case_references: set[str] = set()
    unresolved_bases: set[str] = set()
    fields = ai_recovery.get('fields') or {}
    raw_text = str(text or '')
    legacy = str(fields.get('raw_case_number') or fields.get('case_number') or '')
    # A date/place uncertainty in another sentence must not erase a readable ID.
    # Periods inside case references are followed by a digit, not whitespace.
    lines = re.split(r'\n|(?<=[.!;])\s+', raw_text)
    declared = ai_recovery.get('case_numbers')
    declared_values = {valid_source_case(value) for value in declared if isinstance(value, str)} if isinstance(declared, list) else set()

    def case_base(value: str) -> str:
        match = re.match(r'\d+/\d{2}\.\d', value)
        return match.group() if match else ''

    def add(raw: str, canonical: str = '') -> None:
        key = canonical or 'unresolved:' + raw.strip().casefold()
        if key not in seen:
            seen.add(key)
            rows.append({'case_number': canonical, 'raw_case_number': raw.strip()})

    for line in lines:
        labels = list(re.finditer(r'\b(?:NPP|NPe|NUIPC|Processo)\b\s*[:\-]?', line, re.IGNORECASE))
        administrative_spans = [(label.end(), labels[index + 1].start() if index + 1 < len(labels) else len(line))
                                for index, label in enumerate(labels) if label.group().upper().startswith(('NPP', 'NPE'))]
        matches = []
        for match in CASE_VISIBLE.finditer(line):
            if any(start <= match.start() < end for start, end in administrative_spans):
                non_case_references.add(valid_source_case(match.group()))
            else:
                matches.append(match)
        looks_like_case = bool(matches or re.search(r'\d+\s*/[^\n]*\.', line))
        if looks_like_case and ALTERNATIVE.search(line):
            ambiguous_cases.update(valid_source_case(match.group()) for match in matches)
            add(line)
        else:
            for match in matches:
                # OCR can split the institution suffix into separate letters.
                # Do not turn its first fragment into a shorter, "ready" case.
                tail = SPACED_SUFFIX_TAIL.match(line[match.end():])
                if tail:
                    raw = match.group() + tail.group()
                    ambiguous_cases.update((valid_source_case(raw), valid_source_case(match.group())))
                    add(raw)
                    continue
                # A short OCR block such as "GD SRP" is one source reference,
                # not a complete "GD" case plus an unrelated model-only ID.
                # Only two multi-character blocks at a line boundary, agreeing
                # with one declared full reading, can resolve automatically.
                # Letter-by-letter fragments above deliberately stay unresolved.
                prefix = valid_source_case(match.group())
                suffix = re.search(r'\.\d([A-Z][A-Z0-9]*)$', prefix)
                grouped_tail = GROUPED_SUFFIX_TAIL.match(line[match.end():]) if suffix and len(suffix.group(1)) <= 3 else None
                if grouped_tail:
                    raw = match.group() + grouped_tail.group()
                    joined = valid_source_case(raw)
                    base = case_base(prefix)
                    readings = {value for value in declared_values if case_base(value) == base}
                    fragmented_cases.add(prefix)
                    if len(grouped_tail.group().split()) == 1 and readings == {joined} and joined:
                        add(raw, joined)
                    else:
                        unresolved_bases.add(base)
                        fragmented_cases.add(joined)
                        add(raw)
                    continue
                value = valid_source_case(match.group())
                if value:
                    add(match.group(), value)

    if isinstance(declared, list):
        for raw in declared:
            if not isinstance(raw, str) or not raw.strip():
                continue
            value = valid_source_case(raw)
            if value and value in non_case_references:
                continue
            # A model-only ID absent from its own visible OCR is unresolved.
            if value and value in seen and value not in ambiguous_cases:
                continue
            if value and value in ambiguous_cases:
                continue
            if value and value in fragmented_cases:
                continue
            if value and case_base(value) in unresolved_bases:
                continue
            add(raw)
    if not rows and legacy:
        add(legacy)
    rows = [row for row in rows if row['case_number'] not in ambiguous_cases or not row['case_number']]
    if source_scope_requires_review(raw_text, ai_recovery):
        # Preserve every possible foreground row for source review. Empty IDs
        # enter the existing numbered confirmation/prepare guard; neither a
        # background-only ID nor an arbitrary first foreground ID becomes ready.
        return [{'case_number': '', 'raw_case_number': row['raw_case_number']} for row in rows] or [
            {'case_number': '', 'raw_case_number': 'Uncertain document scope; review the intended source.'}]
    return rows
