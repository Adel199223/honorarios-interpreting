from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

PRIVATE_PATHS = [
    "config/profile.json",
    "config/email.json",
    "config/*.local.json",
    "data/gmail-draft-log.json",
    "data/duplicate-index.json",
    "data/profile-change-log.json",
    "data/precedents.json",
    "data/*.local.json",
    "output/",
    "tmp/",
    ".playwright-mcp/",
    "AGENTS.md",
]
REQUIRED_PUBLIC_FILES = [
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    ".github/workflows/python-package.yml",
]

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".playwright-mcp", "output", "tmp"}
SKIP_FILES = {"scripts/public_release_gate.py"}
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
PRIVATE_PATTERNS = [
    ("iban", re.compile(r"\bPT\d{23}\b", re.IGNORECASE)),
    ("personal_name", re.compile(r"\bAdel\s+Belghali\b", re.IGNORECASE)),
    ("personal_address", re.compile(r"Rua\s+Lu[íi]s\s+de\s+Cam[õo]es", re.IGNORECASE)),
    ("real_court_email", re.compile(r"\b[A-Z0-9._%+\-]+@tribunais\.org\.pt\b", re.IGNORECASE)),
    ("private_user_path", re.compile(r"C:[\\/]+Users[\\/]+FA507[^\s\"'`<>]+", re.IGNORECASE)),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b")),
    ("google_client_secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_\-]{10,}\b")),
]


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _matches_existing_paths(root: Path) -> list[str]:
    blocked: list[str] = []
    for pattern in PRIVATE_PATHS:
        if pattern.endswith("/"):
            path = root / pattern.rstrip("/")
            if path.exists():
                blocked.append(pattern)
            continue
        if "*" in pattern:
            for match in root.glob(pattern):
                if match.exists():
                    blocked.append(match.relative_to(root).as_posix())
            continue
        path = root / pattern
        if path.exists():
            blocked.append(pattern)

    for screenshot in root.glob("*.png"):
        blocked.append(screenshot.name)
    return sorted(set(blocked))


def _missing_public_metadata(root: Path) -> list[str]:
    return [relative for relative in REQUIRED_PUBLIC_FILES if not (root / relative).exists()]


def _iter_scannable_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.relative_to(root).as_posix() in SKIP_FILES:
            continue
        parts = set(path.relative_to(root).parts)
        if parts & SKIP_DIRS:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > 1_500_000:
                continue
        except OSError:
            continue
        files.append(path)
    return files


def _scan_content(root: Path, *, max_findings: int = 100) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in _iter_scannable_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for kind, pattern in PRIVATE_PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append({
                    "kind": kind,
                    "path": _relative(path, root),
                    "line": line,
                    "match_preview": match.group(0)[:80],
                })
                if len(findings) >= max_findings:
                    return findings
    return findings


def analyze_public_readiness(root: str | Path = ROOT, *, require_git: bool = True) -> dict[str, Any]:
    root_path = Path(root).resolve()
    blocked_paths = _matches_existing_paths(root_path)
    metadata_blockers = _missing_public_metadata(root_path)
    content_findings = _scan_content(root_path)
    git_repo = (root_path / ".git").exists()
    git_blockers = [] if git_repo or not require_git else ["Workspace is not a git repository."]
    blocker_count = len(blocked_paths) + len(metadata_blockers) + len(content_findings) + len(git_blockers)
    return {
        "status": "ready" if blocker_count == 0 else "blocked",
        "public_ready": blocker_count == 0,
        "root": str(root_path),
        "git_repo": git_repo,
        "git_blockers": git_blockers,
        "blocked_paths": blocked_paths,
        "metadata_blockers": metadata_blockers,
        "content_findings": content_findings,
        "blocker_count": blocker_count,
        "message": (
            "Publish candidate passed the local privacy and repository metadata gate."
            if blocker_count == 0
            else "Public GitHub publishing is blocked until private paths, missing metadata, and content findings are fixed."
        ),
        "send_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the public release privacy/readiness gate.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--no-require-git", action="store_true", help="Do not require .git to exist.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args(argv)

    report = analyze_public_readiness(args.root, require_git=not args.no_require_git)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["message"])
        print(f"Blockers: {report['blocker_count']}")
        for path in report["blocked_paths"][:20]:
            print(f" - private path: {path}")
        for path in report["metadata_blockers"]:
            print(f" - missing metadata: {path}")
        for finding in report["content_findings"][:20]:
            print(f" - {finding['kind']}: {finding['path']}:{finding['line']}")
        for blocker in report["git_blockers"]:
            print(f" - git: {blocker}")
    return 0 if report["public_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
