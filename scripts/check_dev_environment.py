"""Read-only verification of the supported checkout environment; no repair or credentials."""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.runtime_doctor import run_runtime_doctor


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def probe_tool(name: str) -> str:
    result = subprocess.run([name, "--version"], capture_output=True, text=True, check=True, timeout=15)
    words = result.stdout.strip().split()
    return words[1] if name == "uv" else words[0].removeprefix("v")


def evaluate_environment(
    root: Path, *, python_version: str, prefix: Path, distributions: dict[str, str],
    probe: Callable[[str], str] = probe_tool,
) -> dict:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    pins = {
        "python": (root / ".python-version").read_text().strip(),
        "node": (root / ".node-version").read_text().strip(),
        "uv": project["tool"]["uv"]["required-version"].removeprefix("=="),
    }
    checks = []

    def record(name: str, ready: bool, expected: str, actual: str) -> None:
        checks.append({"name": name, "status": "ready" if ready else "blocked", "expected": expected, "actual": actual})

    record("python", python_version == pins["python"], pins["python"], python_version)
    isolated = prefix.resolve().parent == root.resolve() and prefix.name.startswith(".venv")
    record("project_environment", isolated, "checkout-local .venv directory", "isolated" if isolated else "other interpreter")
    for tool in ("uv", "node"):
        try:
            actual = probe(tool)
        except (OSError, subprocess.SubprocessError, IndexError):
            actual = "unavailable"
        record(tool, actual == pins[tool], pins[tool], actual)

    expected_versions = {normalize(p["name"]): p["version"] for p in lock["package"] if "version" in p}
    installed = {normalize(name): version for name, version in distributions.items()}
    required = project["project"]["dependencies"] + project["project"]["optional-dependencies"]["dev"]
    required_names = {normalize(re.split(r"[<>=!~;\[]", requirement, 1)[0].strip()) for requirement in required}
    # Check every installed locked distribution plus required direct dependencies.
    # Optional platform-only dependencies absent on this platform are not false failures.
    for name in sorted(required_names | (installed.keys() & expected_versions.keys())):
        expected = expected_versions.get(name, "missing lock entry")
        actual = installed.get(name, "missing")
        record("package:" + name, expected == actual, expected, actual)
    return {
        "status": "ready" if all(c["status"] == "ready" for c in checks) else "blocked",
        "checks": checks, "write_allowed": False, "send_allowed": False, "managed_data_changed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = evaluate_environment(
            ROOT, python_version=sys.version.split()[0], prefix=Path(sys.prefix),
            distributions={d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        )
        doctor = run_runtime_doctor().safe_summary()
        report["runtime_status"] = doctor["status"]
        if doctor["status"] != "ready":
            report["status"] = "blocked"
        for module in ("xml.dom.minidom", "html.entities", "ssl", "sqlite3", "venv", "fastapi", "pypdf", "reportlab", "openai"):
            try:
                importlib.import_module(module)
            except (ImportError, OSError):
                report["status"] = "blocked"
                report.setdefault("failed_imports", []).append(module)
    except (OSError, KeyError, ValueError):
        report = {"status": "blocked", "reason": "Missing or invalid tracked environment configuration."}
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print("Development environment: " + report["status"])
        for check in report.get("checks", []):
            if check["status"] != "ready":
                print(f"{check['name']}: expected {check['expected']}; found {check['actual']}")
        if report.get("failed_imports"):
            print("Incomplete interpreter or package imports: " + ", ".join(report["failed_imports"]))
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
