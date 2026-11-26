"""Antigravity PreToolUse hook enforcing draft-only Gmail policy on run_command."""
from __future__ import annotations

import json
import re
import sys

FORBIDDEN_GMAIL_MUTATION_RE = re.compile(
    r"(?:^|[;&|\r\n]+)\s*(?:\$env:[A-Z0-9_]+\s*=\s*[^;\r\n]+[;\s]*)*"
    r"(?:&\s*)?(?:[\"']?[^\s\"']*[/\\])?gmail(?:\.cmd|\.exe)?[\"']?\s+"
    r"mutate\s+(?:send|send-draft|send-with-attachment|reply|forward)\b",
    re.IGNORECASE,
)


def inspect_command(command_line: str) -> dict[str, str]:
    text = str(command_line or "")
    if FORBIDDEN_GMAIL_MUTATION_RE.search(text):
        return {
            "decision": "force_ask",
            "reason": (
                "Blocked automatic Gmail send, reply, or forward command under Honorários "
                "draft-only policy. Only proceed if the user explicitly reviewed and authorized sending."
            ),
        }
    return {"decision": "allow"}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"decision": "allow"}))
        return 0
    tool_call = payload.get("toolCall") if isinstance(payload, dict) else None
    args = tool_call.get("args") if isinstance(tool_call, dict) else None
    command_line = args.get("CommandLine", "") if isinstance(args, dict) else ""
    print(json.dumps(inspect_command(str(command_line or ""))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
