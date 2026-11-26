"""Build a validated Antigravity Gmail CLI draft-only command from a prepared draft payload."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.build_email_draft import file_sha256, validate_draft_payload
    from scripts.generate_pdf import IntakeError, ROOT
except ModuleNotFoundError:
    from build_email_draft import file_sha256, validate_draft_payload
    from generate_pdf import IntakeError, ROOT


DEFAULT_BODY_DIR = ROOT / "tmp" / "gmail-handoff-bodies"
FORBIDDEN_CMD_UNSPACED_META = re.compile(r"(?<!\s)[&|<>](?!\s)")


def _ps_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _windows_cmd_safe_subject(subject: str) -> tuple[str, list[str]]:
    text = str(subject or "").strip()
    warnings: list[str] = []
    if '"' in text:
        raise IntakeError('Email subject cannot contain double quotes (") for Windows gmail.cmd CLI handoff.')
    if "%" in text:
        text = text.replace("%", "%%")
        warnings.append("Escaped '%' as '%%' in --subject for Windows gmail.cmd compatibility.")
    if FORBIDDEN_CMD_UNSPACED_META.search(text):
        warnings.append("Subject contains unspaced &, |, <, or >; verify quoting before invoking gmail.cmd on Windows.")
    return text, warnings


def build_antigravity_gmail_handoff(
    payload_path: str | Path,
    *,
    body_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_payload = Path(payload_path).resolve()
    if not resolved_payload.is_file():
        raise IntakeError(f"Prepared draft payload does not exist: {resolved_payload}")
    try:
        payload = json.loads(resolved_payload.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IntakeError(f"Unable to read prepared draft payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise IntakeError("Prepared draft payload must be a JSON object.")

    errors = validate_draft_payload(payload)
    if errors:
        raise IntakeError("Prepared draft payload is not ready for Gmail handoff: " + "; ".join(errors))

    args = payload["gmail_create_draft_args"]
    recorded_hashes = payload.get("attachment_sha256")
    actual_hashes: dict[str, str] = {}
    attachment_files = [str(item) for item in args["attachment_files"]]
    for item in attachment_files:
        path = Path(item)
        digest = file_sha256(path)
        actual_hashes[str(path)] = digest
        if isinstance(recorded_hashes, dict) and str(path) in recorded_hashes:
            if recorded_hashes[str(path)] != digest:
                raise IntakeError(f"Attachment SHA-256 changed since preparation: {path.name}")

    target_dir = Path(body_dir).resolve() if body_dir is not None else DEFAULT_BODY_DIR.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    body_text = str(args["body"])
    body_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()[:12]
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", resolved_payload.stem).strip(".-") or "draft"
    body_file = target_dir / f"{safe_stem}-{body_hash}.txt"
    body_file.write_text(body_text, encoding="utf-8", newline="\n")

    subject_cli, warnings = _windows_cmd_safe_subject(str(args["subject"]))
    file_flags = " ".join(f"--file {_ps_single_quote(path)}" for path in attachment_files)
    cli_command = (
        f"gmail mutate create-draft "
        f"--to {_ps_single_quote(str(args['to']))} "
        f"--subject {_ps_single_quote(subject_cli)} "
        f"--body-file {_ps_single_quote(str(body_file))} "
        f"{file_flags}"
    ).strip()
    powershell_command = f'$env:AGY_UNATTENDED = "1"; {cli_command}'
    followup_record_command = (
        ".\\.venv311\\Scripts\\python.exe scripts/record_gmail_draft.py "
        f"--payload {_ps_single_quote(str(resolved_payload))} "
        "--draft-id <DRAFT_ID> --message-id <MESSAGE_ID> --thread-id <THREAD_ID>"
    )

    return {
        "status": "ready",
        "mode": "antigravity_gmail_cli_handoff",
        "payload_path": str(resolved_payload),
        "body_file": str(body_file),
        "to": str(args["to"]),
        "subject": str(args["subject"]),
        "attachment_files": attachment_files,
        "attachment_sha256": actual_hashes,
        "unattended_env": {"AGY_UNATTENDED": "1"},
        "cli_command": cli_command,
        "powershell_command": powershell_command,
        "get_draft_command": "gmail readonly get-draft <DRAFT_ID>",
        "followup_record_command": followup_record_command,
        "warnings": warnings,
        "draft_only": True,
        "send_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True, type=Path, help="Prepared *.draft.json payload path.")
    parser.add_argument("--body-dir", type=Path, default=None, help="Directory for UTF-8 --body-file output.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args(argv)

    try:
        result = build_antigravity_gmail_handoff(args.payload, body_dir=args.body_dir)
    except (IntakeError, OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"status": "blocked", "message": str(exc), "draft_only": True, "send_allowed": False}, ensure_ascii=False, indent=2))
        else:
            print(f"Cannot build Antigravity Gmail handoff: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Draft-only Antigravity Gmail CLI command:")
        print(result["powershell_command"])
        print("\nAfter creating the draft, record the returned IDs locally:")
        print(result["followup_record_command"])
        for warning in result["warnings"]:
            print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
