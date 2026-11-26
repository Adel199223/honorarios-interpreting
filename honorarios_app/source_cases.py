"""Separate visible case references without joining alternatives into one ID."""
from __future__ import annotations

import re
import unicodedata
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


def documentary_case_references(text: str, ai_recovery: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Identify only positively bound document-acquisition references.

    Occurrences, not whole cases or body paragraphs, are classified. Any other
    occurrence keeps that case available for ordinary source review. Folded
    text carries a raw-offset map, including decomposed Unicode accents.
    """
    raw = str(text or '')
    if not raw or len(raw) > 100_000 or source_scope_requires_review(raw, ai_recovery or {}):
        return []
    letters, offsets = [], []
    for index, value in enumerate(raw):
        for char in unicodedata.normalize('NFD', value):
            if not unicodedata.combining(char):
                letters.append(char.lower())
                offsets.append(index)
    folded = ''.join(letters)
    matches = list(CASE_VISIBLE.finditer(folded))
    classified = []
    ordinary = set()
    directive = re.compile(r'\b(?:junte|juntar|juncao|requisite|requisitar|requisicao|'
                           r'solicite|solicitar|solicitacao|remeta|remeter|extraia|extrair)\b')
    for match in matches:
        case = valid_source_case(match.group())
        left = max(0, match.start() - 420)
        prefix = folded[left:match.start()]
        # A real new sentence/paragraph or labelled case header ends a directive.
        boundaries = list(re.finditer(r'[.!?;](?:\s+|$)|\n\s*\n|'
                                     r'\n(?=\s*(?:processo|nuipc)\s*[:\-]?)', prefix))
        if boundaries:
            left += boundaries[-1].end()
            prefix = folded[left:match.start()]
        starts = list(directive.finditer(prefix))
        start = starts[-1].start() if starts else -1
        context = prefix[start:] if start >= 0 else ''
        documents = list(re.finditer(r'\b(?:certidao|copia)\b', context))
        after_document = context[documents[-1].end():] if documents else ''
        target_after_document = re.search(
            r'\b(?:(?:aos|nos|para\s+os)\s+autos|(?:ao|para\s+o)\s+(?:processo|inquerito))\b',
            after_document)
        positive = bool(context and documents and not target_after_document
                        # The case supplies the document, rather than being the
                        # target of "junte ao processo" / "remeta para o caso".
                        and re.search(r'\b(?:do|de|(?:proferid[oa]|deduzid[oa]|extraid[oa])\s+no)\s+'
                                      r'(?:inquerito|processo|nuipc)\b\s*(?:n\s*\.?\s*[º°o]?\s*)?[:\-]?\s*$', context)
                        and not re.search(r'\b(?:interprete|interpretacao|tradutor|comparecer|nomead[oa])\b', context)
                        and not ALTERNATIVE.search(context))
        if positive:
            excerpt_start = offsets[left + start]
            raw_start, raw_end = offsets[match.start()], offsets[match.end() - 1] + 1
            end = min(len(raw), raw_end + 100)
            ending = re.search(r'[.!?;](?=\s|$)|\n\s*\n', raw[raw_end:end])
            if ending:
                end = raw_end + ending.end()
            classified.append({'case_number': case, 'raw_case_number': raw[raw_start:raw_end],
                               'excerpt': raw[excerpt_start:end].strip(),
                               'reason': 'Document acquisition/copy reference; not a separate interpreting assignment.',
                               'start': raw_start, 'end': raw_end})
        else:
            ordinary.add(case)
    for item in classified:
        item['documentary_only'] = item['case_number'] not in ordinary
    return classified


def documentary_case_role_error(intake: dict[str, Any]) -> str:
    """Recompute selection from current source, never trust a derived flag/list."""
    case = valid_source_case(intake.get('case_number'))
    ai = intake.get('ai_recovery') if isinstance(intake.get('ai_recovery'), dict) else {}
    raw = str(intake.get('source_text') or '')
    references = documentary_case_references(raw, ai)
    if (source_scope_requires_review(raw, ai) and case
            and any(item['case_number'] == case for item in documentary_case_references(raw))):
        return 'Document membership is uncertain. Review the intended service case before preparing a fee request.'
    if case and any(item['case_number'] == case and item['documentary_only'] for item in references):
        return (f'{case} appears only in a documentary cross-reference in this source. '
                'Review the foreground service case before preparing a fee request.')
    return ''


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
    documentary_only = {item['case_number'] for item in documentary_case_references(raw_text, ai_recovery)
                        if item['documentary_only']}
    legacy = str(fields.get('raw_case_number') or fields.get('case_number') or '')
    # A date/place uncertainty in another sentence or OCR column must not erase a readable ID.
    # Periods inside case references are followed by a digit, not whitespace.
    lines = re.split(r'\n|\s*\|\s*|(?<=[.!;])\s+', raw_text)
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
            if valid_source_case(match.group()) in documentary_only:
                continue
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
            if value and value in non_case_references | documentary_only:
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
    if not rows and legacy and valid_source_case(legacy) not in documentary_only:
        add(legacy)
    if not rows and documentary_only:
        add('Only documentary cross-references were found; review the service case.')
    rows = [row for row in rows if row['case_number'] not in ambiguous_cases or not row['case_number']]
    if source_scope_requires_review(raw_text, ai_recovery):
        # Preserve every possible foreground row for source review. Empty IDs
        # enter the existing numbered confirmation/prepare guard; neither a
        # background-only ID nor an arbitrary first foreground ID becomes ready.
        return [{'case_number': '', 'raw_case_number': row['raw_case_number']} for row in rows] or [
            {'case_number': '', 'raw_case_number': 'Uncertain document scope; review the intended source.'}]
    return rows
