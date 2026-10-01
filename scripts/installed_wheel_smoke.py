"""Build and test the local wheel away from the checkout, using synthetic data only.

The provided Python environment supplies the frozen build/runtime dependencies.
Only this app's local wheel is installed, offline and without dependencies, into
a temporary target. No server is started and all API requests stay in process.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_PROGRAM = "from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])"
RUNTIME_PROGRAM = r'''
import importlib.metadata
import json
from pathlib import Path
import socket
import sys
import threading
from unittest.mock import patch

installed = Path(sys.argv[1]).resolve()
runtime = Path(sys.argv[2]).resolve()
result_path = Path(sys.argv[3])
sys.path.insert(0, str(installed))

def block_network(*args, **kwargs):
    raise AssertionError("Installed-wheel smoke must not make network connections.")

original_connect = socket.socket.connect
original_socketpair = socket.socketpair
socketpair_context = threading.local()

def guarded_connect(sock, address):
    if getattr(socketpair_context, "active", False):
        return original_connect(sock, address)
    return block_network(sock, address)

def internal_socketpair(*args, **kwargs):
    # Windows asyncio uses a local socketpair for its own wake-up pipe.
    # Permit only that library operation on this thread, never app connections.
    socketpair_context.active = True
    try:
        return original_socketpair(*args, **kwargs)
    finally:
        socketpair_context.active = False

with patch.object(socket.socket, "connect", guarded_connect), patch.object(socket.socket, "connect_ex", block_network), patch.object(socket, "create_connection", block_network), patch.object(socket, "socketpair", internal_socketpair):
    from fastapi.testclient import TestClient
    from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides, synthetic_profile, synthetic_service_profiles
    from honorarios_app.web import create_app
    from scripts.create_intake import build_intake
    from scripts.generate_pdf import DEFAULT_TEMPLATE, PACKAGED_DEFAULT_TEMPLATE, build_rendered_request, generate_pdf, render_html
    from scripts.legalpdf_adapter_caller import run_adapter_readiness_result

    distribution = importlib.metadata.distribution("honorarios-interpreting")
    entrypoint = next(item for item in distribution.entry_points if item.group == "console_scripts" and item.name == "honorarios-web")
    assert callable(entrypoint.load())
    assert Path(distribution.locate_file("honorarios_app")).resolve().is_relative_to(installed)
    assert DEFAULT_TEMPLATE == PACKAGED_DEFAULT_TEMPLATE
    assert DEFAULT_TEMPLATE.is_file() and DEFAULT_TEMPLATE.resolve().is_relative_to(installed)

    create_synthetic_runtime(runtime)
    app = create_app(**runtime_path_overrides(runtime))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        page = client.get("/")
        assert page.status_code == 200 and "LegalPDF Honorários" in page.text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/style.css").status_code == 200
        def fetch_json(url):
            from urllib.parse import urlparse
            response = client.get(urlparse(url).path)
            response.raise_for_status()
            return response.json()
        readiness = run_adapter_readiness_result("http://127.0.0.1", fetch_json=fetch_json)
        assert readiness.status == "ready", readiness.safe_summary()
        assert readiness.send_allowed is False and readiness.write_allowed is False
        assert readiness.isolated_synthetic_runtime is True

    intake = build_intake(profile_name="example_interpreting", case_number="123/26.0WHEEL", service_date="2026-05-04", closing_date="2026-05-04", profiles=synthetic_service_profiles())
    rendered = build_rendered_request(intake, synthetic_profile())
    html_path = runtime / "output" / "installed-wheel.html"
    pdf_path = runtime / "output" / "installed-wheel.pdf"
    render_html(DEFAULT_TEMPLATE, rendered, html_path)
    generate_pdf(rendered, pdf_path)
    html = html_path.read_text(encoding="utf-8")
    assert "123/26.0WHEEL" in html and "{{ " not in html
    assert pdf_path.read_bytes().startswith(b"%PDF-")

    loaded = {name: Path(module.__file__).resolve() for name, module in sys.modules.items() if (name == "honorarios_app" or name.startswith("honorarios_app.") or name == "scripts" or name.startswith("scripts.")) and getattr(module, "__file__", None)}
    assert loaded and all(path.is_relative_to(installed) for path in loaded.values()), "Checkout imports must not satisfy the installed-wheel smoke."
    assert not (installed / "config").exists() and not (installed / "data").exists()
    assert not (installed / "output").exists() and not (installed / "tmp").exists()

result_path.write_text(json.dumps({"status": "ready", "installed_module_count": len(loaded), "package_imports_from_installed_target": True, "packaged_template_rendered": True, "synthetic_pdf_generated": True, "browser_assets_present": True, "adapter_readiness": readiness.safe_summary(), "network_allowed": False, "live_data_read": False, "send_allowed": False, "legalpdf_write_allowed": False}), encoding="utf-8")
'''


def _copy_build_sources(project_root: Path, target: Path) -> None:
    """Copy an allowlist of source files; exclude local overlays and runtime data."""
    target.mkdir(parents=True)
    for filename in ("pyproject.toml", "README.md"):
        shutil.copy2(project_root / filename, target / filename)
    for directory, extensions in (
        ("honorarios_app", {".py", ".html", ".css", ".js"}),
        ("scripts", {".py", ".mjs"}),
    ):
        for source in (project_root / directory).rglob("*"):
            if not source.is_file() or source.suffix not in extensions or "__pycache__" in source.parts:
                continue
            destination = target / source.relative_to(project_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode:
        details = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Wheel smoke command failed ({completed.returncode}): {details[-4000:]}")


def run_installed_wheel_smoke(
    *,
    project_root: Path = PROJECT_ROOT,
    python_executable: str = sys.executable,
    uv_executable: str | None = None,
) -> dict[str, Any]:
    uv = uv_executable or shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required for offline local-wheel installation; use --uv with the pinned executable.")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    with tempfile.TemporaryDirectory(prefix="honorarios-installed-wheel-") as temporary:
        root = Path(temporary)
        source = root / "build-source"
        wheels = root / "wheels"
        installed = root / "installed"
        cwd = root / "outside-checkout"
        wheels.mkdir()
        cwd.mkdir()
        _copy_build_sources(project_root.resolve(), source)
        _run([python_executable, "-I", "-c", BUILD_PROGRAM, str(wheels)], cwd=source, env=env)
        built = list(wheels.glob("*.whl"))
        if len(built) != 1:
            raise RuntimeError("Expected exactly one built Honorários wheel.")
        wheel = built[0]
        with zipfile.ZipFile(wheel) as archive:
            entries = archive.namelist()
        if any(entry.startswith(("config/", "data/", "output/", "tmp/")) or "/.env" in entry for entry in entries):
            raise RuntimeError("Wheel must contain source/assets only, without private runtime data.")
        _run([str(uv), "--no-config", "pip", "install", "--offline", "--no-deps", "--python", python_executable, "--target", str(installed), str(wheel)], cwd=cwd, env=env)
        result_path = root / "result.json"
        _run([python_executable, "-I", "-c", RUNTIME_PROGRAM, str(installed), str(root / "synthetic-runtime"), str(result_path)], cwd=cwd, env=env)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["wheel"] = wheel.name
        result["checkout_pythonpath_used"] = False
        result["private_runtime_bundled"] = False
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and test the Honorários wheel in an isolated target without network or live data.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--uv", help="Path to the pinned uv executable for offline installation.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_installed_wheel_smoke(project_root=args.project_root, python_executable=args.python, uv_executable=args.uv)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result = {"status": "blocked", "message": str(exc), "send_allowed": False, "network_allowed": False}
    print(json.dumps(result, ensure_ascii=True, indent=2) if args.json else f"Installed-wheel smoke: {result['status']}" + (f" ({result['message']})" if "message" in result else ""))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
