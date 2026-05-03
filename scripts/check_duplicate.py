from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.generate_pdf import (
        DEFAULT_DUPLICATE_INDEX,
        IntakeError,
        find_duplicate_record,
        format_duplicate_message,
        load_json,
    )
except ModuleNotFoundError:
    from generate_pdf import (
        DEFAULT_DUPLICATE_INDEX,
        IntakeError,
        find_duplicate_record,
        format_duplicate_message,
        load_json,
    )


def intake_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.intake:
        return load_json(args.intake)
    if args.case_number and args.service_date:
        return {
            "case_number": args.case_number,
            "service_date": args.service_date,
        }
    raise IntakeError("Provide an intake JSON file, or both --case-number and --service-date.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether an interpreting honorários request is probably a duplicate.")
    parser.add_argument("intake", nargs="?", type=Path, help="Path to intake JSON.")
    parser.add_argument("--case-number", help="Case number to check.")
    parser.add_argument("--service-date", help="Service date in YYYY-MM-DD.")
    parser.add_argument("--duplicate-index", type=Path, default=DEFAULT_DUPLICATE_INDEX, help="Path to duplicate index JSON.")
    args = parser.parse_args(argv)

    try:
        intake = intake_from_args(args)
        duplicate = find_duplicate_record(intake, args.duplicate_index, strict=True)
    except (IntakeError, json.JSONDecodeError, OSError) as exc:
        print(f"Cannot check duplicate: {exc}", file=sys.stderr)
        return 2

    if duplicate:
        print(format_duplicate_message(duplicate))
        return 3

    print("No duplicate found for this case number and service date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
