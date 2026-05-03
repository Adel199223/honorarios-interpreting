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
