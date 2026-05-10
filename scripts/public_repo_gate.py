from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HOOKS_PATH = ".githooks"
EXPECTED_PRE_COMMIT_COMMAND = "python scripts/public_repo_gate.py --staged"

TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
MAX_TEXT_BYTES = 1_500_000

BLOCKED_PATH_PATTERNS = [
    ("AGENTS.md", "local machine/project operating instructions"),
    (".env", "environment secrets"),
    (".env.*", "environment secrets"),
    ("config/email.json", "local email defaults"),
    ("config/profile.json", "local personal/payment profile"),
    ("config/*.local.json", "local credentials or runtime config"),
    ("config/*token*.json", "local OAuth token material"),
    ("data/duplicate-index.json", "local duplicate history"),
    ("data/gmail-draft-log.json", "local Gmail draft history"),
    ("data/precedents.json", "local case precedent history"),
    ("data/profile-change-log.json", "local profile change history"),
    ("data/court-emails.json", "local recipient directory"),
    ("data/known-destinations.json", "local destination history"),
    ("data/service-profiles.json", "local service profile data"),
    ("data/*.local.json", "local runtime data"),
]
BLOCKED_PATH_PREFIXES = {
    ".playwright-mcp/": "browser automation runtime",
    ".tmp-test/": "temporary test runtime",
    ".worktrees/": "local worktree storage",
    "output/": "generated artifacts",
    "tmp/": "temporary runtime artifacts",
}
BLOCKED_ARTIFACT_SUFFIXES = {
    ".heic",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}

PRIVATE_PATTERNS = [
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b")),
    ("google_client_secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_\-]{10,}\b")),
    ("google_access_token", re.compile(r"\bya29\.[A-Za-z0-9_\-\.]+\b")),
    ("google_refresh_token", re.compile(r"\b1//[A-Za-z0-9_\-\.]{20,}\b")),
    ("github_token", re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}\b")),
    ("iban", re.compile(r"\bPT\d{23}\b", re.IGNORECASE)),
    ("personal_name", re.compile(r"\bAdel\s+Belghali\b", re.IGNORECASE)),
    ("personal_address", re.compile(r"Rua\s+Lu[íi]s\s+de\s+Cam[õo]es", re.IGNORECASE)),
    ("real_court_email", re.compile(r"\b[A-Z0-9._%+\-]+@tribunais\.org\.pt\b", re.IGNORECASE)),
    ("private_user_path", re.compile(r"C:[\\/]+Users[\\/]+FA507[^\s\"'`<>]+", re.IGNORECASE)),
]


@dataclass(frozen=True)
class CandidateFile:
    path: str
    content: bytes | None


def _normalize_path(path: str | Path) -> str:
    normalized = str(path).replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _safe_hooks_path_label(value: str) -> str:
    normalized = value.strip().replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    if normalized == EXPECTED_HOOKS_PATH:
        return EXPECTED_HOOKS_PATH
    return "[custom]"


def _path_blocker(path: str) -> dict[str, str] | None:
    normalized = _normalize_path(path)
    for prefix, reason in BLOCKED_PATH_PREFIXES.items():
        if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
            return {"path": normalized, "reason": reason}
    for pattern, reason in BLOCKED_PATH_PATTERNS:
        if fnmatch.fnmatchcase(normalized, pattern):
            return {"path": normalized, "reason": reason}
    if Path(normalized).suffix.lower() in BLOCKED_ARTIFACT_SUFFIXES:
        return {"path": normalized, "reason": "binary generated/source artifact"}
    return None


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _content_findings(candidate: CandidateFile, *, max_findings: int) -> list[dict[str, Any]]:
    if candidate.content is None or len(candidate.content) > MAX_TEXT_BYTES:
        return []
    if Path(candidate.path).suffix.lower() not in TEXT_SUFFIXES:
        return []
    text = candidate.content.decode("utf-8", errors="ignore")
    findings: list[dict[str, Any]] = []
    for kind, pattern in PRIVATE_PATTERNS:
        for match in pattern.finditer(text):
            findings.append({
                "kind": kind,
                "path": candidate.path,
                "line": _line_number(text, match.start()),
                "match_preview": match.group(0)[:80],
            })
            if len(findings) >= max_findings:
                return findings
    return findings


def analyze_candidates(candidates: Iterable[CandidateFile], *, max_findings: int = 100) -> dict[str, Any]:
    path_blockers: list[dict[str, str]] = []
    content_findings: list[dict[str, Any]] = []
    scanned_paths: list[str] = []

    for candidate in candidates:
        normalized = _normalize_path(candidate.path)
        scanned_paths.append(normalized)
        blocker = _path_blocker(normalized)
        if blocker:
            path_blockers.append(blocker)
        if len(content_findings) < max_findings:
            content_findings.extend(_content_findings(
                CandidateFile(normalized, candidate.content),
                max_findings=max_findings - len(content_findings),
            ))

    blocked = bool(path_blockers or content_findings)
    return {
        "status": "blocked" if blocked else "ready",
        "public_repo_ready": not blocked,
        "scanned_count": len(scanned_paths),
        "scanned_paths": sorted(scanned_paths),
        "path_blockers": sorted(path_blockers, key=lambda item: item["path"]),
        "content_findings": content_findings,
        "blocker_count": len(path_blockers) + len(content_findings),
        "message": (
            "Public repo gate passed."
            if not blocked
            else "Public repo gate blocked private paths or sensitive content."
        ),
        "send_allowed": False,
    }


def _staged_candidates(root: Path) -> tuple[list[CandidateFile], list[str]]:
    names = _run_git(root, ["diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z"])
    if names.returncode != 0:
        return [], [names.stderr.strip() or "Unable to read staged files."]
    paths = [path for path in names.stdout.split("\0") if path]
    candidates: list[CandidateFile] = []
    errors: list[str] = []
    for path in paths:
        blob = subprocess.run(
            ["git", "show", f":{path}"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if blob.returncode != 0:
            errors.append(blob.stderr.decode("utf-8", errors="ignore").strip() or f"Unable to read staged blob: {path}")
            candidates.append(CandidateFile(path, None))
            continue
        candidates.append(CandidateFile(path, blob.stdout))
    return candidates, errors


def _tracked_candidates(root: Path) -> tuple[list[CandidateFile], list[str]]:
    names = _run_git(root, ["ls-files", "-z"])
    if names.returncode != 0:
        return [], [names.stderr.strip() or "Unable to read tracked files."]
    paths = [path for path in names.stdout.split("\0") if path]
    candidates: list[CandidateFile] = []
    errors: list[str] = []
    for path in paths:
        absolute = root / path
        try:
            candidates.append(CandidateFile(path, absolute.read_bytes()))
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            candidates.append(CandidateFile(path, None))
    return candidates, errors


def analyze_staged(root: str | Path = ROOT, *, max_findings: int = 100) -> dict[str, Any]:
    root_path = Path(root).resolve()
    candidates, errors = _staged_candidates(root_path)
    report = analyze_candidates(candidates, max_findings=max_findings)
    report["mode"] = "staged"
    report["root"] = str(root_path)
    report["errors"] = errors
    if errors:
        report["status"] = "blocked"
        report["public_repo_ready"] = False
        report["blocker_count"] += len(errors)
    return report


def analyze_tracked(root: str | Path = ROOT, *, max_findings: int = 100) -> dict[str, Any]:
    root_path = Path(root).resolve()
    candidates, errors = _tracked_candidates(root_path)
    report = analyze_candidates(candidates, max_findings=max_findings)
    report["mode"] = "tracked"
    report["root"] = str(root_path)
    report["errors"] = errors
    if errors:
        report["status"] = "blocked"
        report["public_repo_ready"] = False
        report["blocker_count"] += len(errors)
    return report


def analyze_hook_config(root: str | Path = ROOT) -> dict[str, Any]:
    root_path = Path(root).resolve()
    config = _run_git(root_path, ["config", "--get", "core.hooksPath"])
    errors: list[str] = []
    if config.returncode not in {0, 1}:
        errors.append(config.stderr.strip() or "Unable to read core.hooksPath.")

    hooks_path = _safe_hooks_path_label(config.stdout)
    hooks_path_ready = hooks_path == EXPECTED_HOOKS_PATH
    pre_commit_hook = root_path / EXPECTED_HOOKS_PATH / "pre-commit"
    pre_commit_hook_present = pre_commit_hook.is_file()
    staged_gate_wired = False
    if pre_commit_hook_present:
        try:
            hook_text = pre_commit_hook.read_text(encoding="utf-8", errors="replace")
            staged_gate_wired = EXPECTED_PRE_COMMIT_COMMAND in hook_text
        except OSError as exc:
            errors.append(f".githooks/pre-commit: {exc}")

    blockers = []
    if not hooks_path_ready:
        blockers.append("core.hooksPath is not configured for .githooks.")
    if not pre_commit_hook_present:
        blockers.append(".githooks/pre-commit is missing.")
    if pre_commit_hook_present and not staged_gate_wired:
        blockers.append(".githooks/pre-commit does not run the staged public repo gate.")
    blockers.extend(errors)

    ready = not blockers
    return {
        "status": "ready" if ready else "blocked",
        "hook_configured": ready,
        "mode": "hook_config",
        "hooks_path": hooks_path,
        "expected_hooks_path": EXPECTED_HOOKS_PATH,
        "pre_commit_hook_present": pre_commit_hook_present,
        "staged_gate_wired": staged_gate_wired,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "message": (
            "Git pre-commit hook is configured to run the staged public repo gate."
            if ready
            else "Git pre-commit hook is not fully configured for the staged public repo gate."
        ),
        "send_allowed": False,
    }


def _print_text_report(report: dict[str, Any]) -> None:
    print(report["message"])
    print(f"Mode: {report.get('mode', 'candidates')}")
    if report.get("mode") == "hook_config":
        print(f"Hooks path: {report.get('hooks_path') or '(not configured)'}")
        print(f"Expected hooks path: {report.get('expected_hooks_path')}")
        print(f"Pre-commit hook present: {report.get('pre_commit_hook_present')}")
        print(f"Staged gate wired: {report.get('staged_gate_wired')}")
        print(f"Blockers: {report.get('blocker_count', 0)}")
        for blocker in report.get("blockers", [])[:10]:
            print(f" - blocker: {blocker}")
        return
    print(f"Scanned files: {report['scanned_count']}")
    print(f"Blockers: {report['blocker_count']}")
    for blocker in report["path_blockers"][:30]:
        print(f" - private path: {blocker['path']} ({blocker['reason']})")
    for finding in report["content_findings"][:30]:
        print(f" - {finding['kind']}: {finding['path']}:{finding['line']}")
    for error in report.get("errors", [])[:10]:
        print(f" - error: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Block private/runtime files from public Git commits.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="Scan staged Git blobs.")
    mode.add_argument("--tracked", action="store_true", help="Scan tracked files.")
    mode.add_argument("--hook-configured", action="store_true", help="Check that core.hooksPath points at .githooks and the pre-commit hook runs the staged gate.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--max-findings", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.hook_configured:
        report = analyze_hook_config(args.root)
    elif args.tracked:
        report = analyze_tracked(args.root, max_findings=args.max_findings)
    else:
        report = analyze_staged(args.root, max_findings=args.max_findings)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_text_report(report)
    ready = report.get("public_repo_ready")
    if ready is None:
        ready = report.get("hook_configured", False)
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
