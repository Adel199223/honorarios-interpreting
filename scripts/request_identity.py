from __future__ import annotations

import re
from typing import Any


def normalize_case_number(value: str) -> str:
    compact = re.sub(r"\s+", "", str(value or "")).upper()
    match = re.match(r"^0*(\d+)(/.*)$", compact)
    if match:
        return f"{int(match.group(1))}{match.group(2)}"
    return compact


def normalize_period_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def request_identity_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        normalize_case_number(str(record.get("case_number") or "")),
        str(record.get("service_date") or "").strip(),
        normalize_period_label(str(record.get("service_period_label") or "")),
    )


def request_identity_keys_overlap(left: tuple[str, str, str], right: tuple[str, str, str]) -> bool:
    """An unspecified period cannot establish a separate same-day service."""
    return bool(left[0] and left[1] and left[:2] == right[:2]
                and (not left[2] or not right[2] or left[2] == right[2]))


def validate_distinct_request_members(requests: list[dict[str, Any]]) -> None:
    """Reject duplicate or ambiguously overlapping members before side effects."""
    seen: list[tuple[str, str, str]] = []
    for index, row in enumerate(requests, start=1):
        if not isinstance(row, dict) or not all(request_identity_key(row)[:2]):
            raise ValueError('Every grouped request needs a case number and service date.')
        key = request_identity_key(row)
        if any(request_identity_keys_overlap(key, previous) for previous in seen):
            raise ValueError(f'Request {index} overlaps an earlier request for the same case/date. Remove the duplicate or specify distinct service periods for both requests.')
        seen.append(key)
