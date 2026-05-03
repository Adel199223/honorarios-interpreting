from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.generate_pdf import ROOT, get_service_date_value, load_json, service_date_conflict, service_date_conflict_is_confirmed
    from scripts.entity_rules import has_pj_host_building, resolve_entities, source_mentions_non_court_service, source_mentions_pj_context
except ModuleNotFoundError:
    from generate_pdf import ROOT, get_service_date_value, load_json, service_date_conflict, service_date_conflict_is_confirmed
    from entity_rules import has_pj_host_building, resolve_entities, source_mentions_non_court_service, source_mentions_pj_context


QUESTION_RULES = [
    {
        "field": "case_number",
        "question": "What is the Número de processo exactly as it appears on the document?",
        "answer_hint": "Example: 398/24.5T8BJA",
    },
    {
        "field": "service_date",
        "question": "What date did you provide the in-person interpreting service?",
        "answer_hint": "Use YYYY-MM-DD. If the image metadata date is the service date, give that date.",
        "unless": "effective_service_date_available",
    },
    {
        "field": "service_date_source",
        "question": "The document date and image metadata date conflict. Which service date should I use?",
        "answer_hint": "Answer with the correct date in YYYY-MM-DD, or say metadata/document.",
        "when": "service_date_conflict",
    },
    {
        "field": "payment_entity",
        "question": "Which court, Ministério Público office, or other entity should this request be addressed to for payment?",
        "answer_hint": "Example: Tribunal de Beja.",
        "unless": "payment_entity_inferred",
    },
    {
        "field": "service_place",
        "question": "Which building and city did Polícia Judiciária use for this service?",
        "answer_hint": "Example: Posto da GNR de Ferreira do Alentejo.",
        "when": "pj_host_building_missing",
    },
    {
        "field": "service_entity",
        "question": "Where did you attend in person for this interpreting service?",
        "answer_hint": "Example: Tribunal de Beja, GNR de Cuba, PSP de Moura.",
        "unless": "service_entity_inferred",
    },
    {
        "field": "claim_transport",
        "question": "Should this request include transport expenses from Marmelar?",
        "answer_hint": "Answer yes or no.",
    },
    {
        "field": "transport.destination",
        "question": "What was the transport destination?",
        "answer_hint": "A city name is enough, for example Beja.",
        "when": "claim_transport",
    },
    {
        "field": "transport.km_one_way",
        "question": "How many kilometers is it one way from Marmelar?",
        "answer_hint": "A number is enough, for example 39.",
        "when": "claim_transport",
    },
    {
        "field": "closing_city",
        "question": "What city should appear in the closing line?",
        "answer_hint": "A city name is enough, for example Beja.",
    },
    {
        "field": "closing_date",
        "question": "What date should appear in the closing line of the request?",
        "answer_hint": "Use YYYY-MM-DD.",
    },
]


def get_nested(data: dict[str, Any], field_path: str) -> Any:
    value: Any = data
    for part in field_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def has_value(data: dict[str, Any], field_path: str) -> bool:
    value = get_nested(data, field_path)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def rule_applies(rule: dict[str, str], intake: dict[str, Any]) -> bool:
    unless = rule.get("unless")
    entities = resolve_entities(intake)
    if unless == "effective_service_date_available":
        try:
            get_service_date_value(intake)
            return False
        except Exception:
            return True
    if unless == "payment_entity_inferred" and entities["payment_entity"]:
        return False
    if unless == "service_entity_inferred":
        if source_mentions_pj_context(intake) and not has_pj_host_building(intake):
            return False
        has_explicit_service_entity = (
            has_value(intake, "service_entity")
            or has_value(intake, "service_place")
            or has_value(intake, "service_place_phrase")
        )
        if source_mentions_non_court_service(intake) and not has_explicit_service_entity:
            return True
        if entities["service_entity"]:
            return False
        return False

    condition = rule.get("when")
    if not condition:
        return True
    if condition == "claim_transport":
        return bool(intake.get("claim_transport"))
    if condition == "service_date_conflict":
        return bool(service_date_conflict(intake)) and not service_date_conflict_is_confirmed(intake)
    if condition == "pj_host_building_missing":
        return source_mentions_pj_context(intake) and not has_pj_host_building(intake)
    return True


def missing_questions(intake: dict[str, Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for rule in QUESTION_RULES:
        if not rule_applies(rule, intake):
            continue
        if rule.get("when") == "service_date_conflict":
            questions.append({**rule, "number": len(questions) + 1})
            continue
        if rule.get("when") == "pj_host_building_missing":
            questions.append({**rule, "number": len(questions) + 1})
            continue
        if not has_value(intake, rule["field"]):
            questions.append({**rule, "number": len(questions) + 1})
    return questions


def format_numbered_questions(questions: list[dict[str, Any]]) -> str:
    if not questions:
        return "No missing information questions."
    lines = ["Please answer the missing items by number. Short answers are fine:"]
    for question in questions:
        lines.append(f"{question['number']}. {question['question']} ({question['answer_hint']})")
    return "\n".join(lines)


def parse_numbered_answers(answer_text: str, questions: list[dict[str, Any]]) -> dict[str, str]:
    question_by_number = {int(question["number"]): question for question in questions}
    answers: dict[str, str] = {}
    for line in answer_text.splitlines():
        match = re.match(r"^\s*(\d+)\s*[\).:\-]?\s*(.+?)\s*$", line)
        if not match:
            continue
        number = int(match.group(1))
        answer = match.group(2).strip()
        question = question_by_number.get(number)
        if question and answer:
            answers[question["field"]] = answer
    return answers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print numbered missing-information questions for an intake JSON.")
    parser.add_argument("intake", type=Path, help="Path to a partial or complete intake JSON.")
    parser.add_argument("--answers", type=Path, help="Optional text file with numbered answers to map back to fields.")
    args = parser.parse_args(argv)

    try:
        intake = load_json(args.intake)
        questions = missing_questions(intake)
        print(format_numbered_questions(questions))
        if args.answers:
            mapped = parse_numbered_answers(args.answers.read_text(encoding="utf-8"), questions)
            print(json.dumps(mapped, ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot inspect intake: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
