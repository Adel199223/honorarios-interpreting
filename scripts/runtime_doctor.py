from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

MINIMUM_PYTHON = (3, 11)
REQUIRED_RUNTIME_MODULES: tuple[dict[str, str], ...] = (
    {"package": "fastapi", "module": "fastapi", "purpose": "local browser API"},
    {"package": "uvicorn", "module": "uvicorn", "purpose": "local server"},
    {"package": "jinja2", "module": "jinja2", "purpose": "browser templates"},
    {"package": "python-multipart", "module": "multipart", "purpose": "safe upload parsing"},
    {"package": "reportlab", "module": "reportlab", "purpose": "PDF rendering"},
    {"package": "pypdf", "module": "pypdf", "purpose": "PDF packet inspection"},
    {"package": "Pillow", "module": "PIL", "purpose": "image source evidence"},
    {"package": "httpx", "module": "httpx", "purpose": "HTTP diagnostics"},
    {"package": "openai", "module": "openai", "purpose": "optional OCR client"},
)


@dataclass(frozen=True)
class RuntimeDoctorResult:
    status: str
    python_version: str
    minimum_python: str
    python_executable: str
    python_ready: bool
    modules_ready: bool
    missing_modules: list[str]
    checks: list[dict[str, Any]]
    send_allowed: bool = False
    write_allowed: bool = False
    managed_data_changed: bool = False

    def safe_summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "python_version": self.python_version,
            "minimum_python": self.minimum_python,
            "python_executable": self.python_executable,
            "python_ready": self.python_ready,
            "module_ready": self.modules_ready,
            "missing_modules": list(self.missing_modules),
            "checks": self.checks,
            "send_allowed": self.send_allowed,
            "write_allowed": self.write_allowed,
            "managed_data_changed": self.managed_data_changed,
        }


def _version_text(version_info: Sequence[int]) -> str:
    parts = list(version_info[:3])
    while len(parts) < 3:
        parts.append(0)
    return ".".join(str(part) for part in parts)


def _minimum_text() -> str:
    return ".".join(str(part) for part in MINIMUM_PYTHON)


def _executable_label(executable: str) -> str:
    name = Path(str(executable or "python")).name
    return name or "python"


def run_runtime_doctor(
    *,
    find_spec: Callable[[str], Any] = importlib.util.find_spec,
    version_info: Sequence[int] = sys.version_info,
    executable: str = sys.executable,
) -> RuntimeDoctorResult:
    python_ready = tuple(version_info[:2]) >= MINIMUM_PYTHON
    checks: list[dict[str, Any]] = [
        {
            "name": "runtime_python_version",
            "status": "ready" if python_ready else "blocked",
            "message": (
                f"Python {_version_text(version_info)} satisfies minimum {_minimum_text()}."
                if python_ready
                else f"Python {_version_text(version_info)} is below minimum {_minimum_text()}."
            ),
        }
    ]
    missing_modules: list[str] = []

    for requirement in REQUIRED_RUNTIME_MODULES:
        module_name = requirement["module"]
        ready = find_spec(module_name) is not None
        if not ready:
            missing_modules.append(requirement["package"])
        checks.append({
            "name": f"runtime_module_{module_name.replace('-', '_')}",
            "status": "ready" if ready else "blocked",
            "module": module_name,
            "package": requirement["package"],
            "purpose": requirement["purpose"],
        })

    modules_ready = not missing_modules
    status = "ready" if python_ready and modules_ready else "blocked"
    return RuntimeDoctorResult(
        status=status,
        python_version=_version_text(version_info),
        minimum_python=_minimum_text(),
        python_executable=_executable_label(executable),
        python_ready=python_ready,
        modules_ready=modules_ready,
        missing_modules=missing_modules,
        checks=checks,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check local Python runtime and dependency readiness without writing data.")
    parser.add_argument("--json", action="store_true", help="Print a JSON readiness summary.")
    args = parser.parse_args(argv)

    result = run_runtime_doctor()
    summary = result.safe_summary()
    if args.json:
        print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    else:
        print(f"status: {summary['status']}")
        print(f"python: {summary['python_version']} ({summary['python_executable']})")
        if summary["missing_modules"]:
            print("missing: " + ", ".join(summary["missing_modules"]))
        else:
            print("missing: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
