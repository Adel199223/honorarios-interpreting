from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

import uvicorn

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from honorarios_app.runtime import (
    SYNTHETIC_DEFAULT_CASE,
    SYNTHETIC_REPLACEMENT_CASE,
    SYNTHETIC_SERVICE_DATE,
    create_synthetic_runtime,
    runtime_path_overrides,
)
from honorarios_app.web import create_app
from scripts.local_app_smoke import run_smoke


SmokeRunner = Callable[..., dict[str, Any]]


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_for_ready(base_url: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/reference", timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"Isolated app did not become ready at {base_url}: {last_error}")


def _start_server(runtime_root: Path, host: str, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    app = create_app(**runtime_path_overrides(runtime_root))
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread


def run_isolated_app_smoke(
    *,
    runtime_root: str | Path | None = None,
    keep_runtime: bool = False,
    host: str = "127.0.0.1",
    port: int = 0,
    start_server: bool = True,
    smoke_runner: SmokeRunner = run_smoke,
    interaction_checks: bool = False,
    source_upload_checks: bool = False,
    supporting_attachment_checks: bool = False,
    gmail_api_checks: bool = False,
    browser_click_through: bool = False,
    browser_upload_photo: bool = False,
    browser_upload_pdf: bool = False,
    browser_upload_supporting_attachment: bool = False,
    browser_correction_mode: bool = False,
    browser_iab_click_through: bool = False,
    browser_profile_proposal: bool = False,
    browser_gmail_api_create: bool = False,
    browser_manual_handoff_stale: bool = False,
    browser_recent_work_lifecycle: bool = False,
    browser_prepare_replacement: bool = False,
    browser_prepare_packet: bool = False,
    browser_record_helper: bool = False,
) -> dict[str, Any]:
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if runtime_root is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="honorarios-isolated-runtime-")
        root = Path(temp_dir.name)
    else:
        root = Path(runtime_root)

    selected_port = port or _free_port(host)
    base_url = f"http://{host}:{selected_port}"
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    previous_fake_gmail = os.environ.get("HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE")
    try:
        seed_active_draft = bool(browser_prepare_replacement or browser_recent_work_lifecycle)
        manifest = create_synthetic_runtime(root, seed_active_draft=seed_active_draft)
        if gmail_api_checks or browser_gmail_api_create:
            os.environ["HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"] = "1"
        if start_server:
            server, thread = _start_server(root, host, selected_port)
            _wait_for_ready(base_url)
        interaction_case_number = SYNTHETIC_REPLACEMENT_CASE if browser_prepare_replacement else SYNTHETIC_DEFAULT_CASE
        report = smoke_runner(
            base_url,
            interaction_checks=interaction_checks,
            source_upload_checks=source_upload_checks,
            supporting_attachment_checks=supporting_attachment_checks,
            gmail_api_checks=gmail_api_checks,
            source_upload_profile="example_interpreting" if source_upload_checks else "",
            interaction_profile="example_interpreting",
            interaction_case_number=interaction_case_number,
            interaction_service_date=SYNTHETIC_SERVICE_DATE,
            browser_click_through=browser_click_through or browser_iab_click_through,
            browser_iab_click_through=browser_iab_click_through,
            browser_upload_photo=browser_upload_photo,
            browser_upload_pdf=browser_upload_pdf,
            browser_upload_supporting_attachment=browser_upload_supporting_attachment,
            browser_correction_mode=browser_correction_mode,
            browser_profile_proposal=browser_profile_proposal,
            browser_gmail_api_create=browser_gmail_api_create,
            browser_manual_handoff_stale=browser_manual_handoff_stale,
            browser_recent_work_lifecycle=browser_recent_work_lifecycle,
            browser_prepare_replacement=browser_prepare_replacement,
            browser_prepare_packet=browser_prepare_packet,
            browser_record_helper=browser_record_helper,
        )
        report["isolated_runtime"] = {
            "runtime_root": str(root.resolve()),
            "base_url": base_url,
            "seed_active_draft": seed_active_draft,
            "seed_active_draft_case": manifest["seed_active_draft_case"],
            "kept": bool(runtime_root is not None or keep_runtime),
            "send_allowed": False,
        }
        report["send_allowed"] = False
        return report
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5)
        if previous_fake_gmail is None:
            os.environ.pop("HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE", None)
        else:
            os.environ["HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"] = previous_fake_gmail
        if temp_dir is not None and not keep_runtime:
            temp_dir.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local app smoke against an isolated synthetic runtime.")
    parser.add_argument("--runtime-root", type=Path, help="Optional runtime folder to keep/reuse. Defaults to a temporary folder.")
    parser.add_argument("--keep-runtime", action="store_true", help="Keep the temporary runtime folder after the smoke run.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--interaction-checks", action="store_true", help="Run API interaction checks against the isolated app. May create isolated PDF/payload artifacts.")
    parser.add_argument("--source-upload-checks", action="store_true", help="Run synthetic source upload evidence checks against the isolated app. Creates isolated source-preview artifacts only.")
    parser.add_argument("--supporting-attachment-checks", action="store_true", help="Run synthetic declaration/proof attachment evidence checks against the isolated app. Creates isolated attachment artifacts only.")
    parser.add_argument("--gmail-api-checks", action="store_true", help="Run synthetic Gmail Draft API create smoke with fake Gmail mode in the isolated runtime.")
    parser.add_argument("--browser-click-through", action="store_true", help="Run browser click-through against the isolated app when Python Playwright is available.")
    parser.add_argument("--browser-iab-click-through", action="store_true", help="Run browser click-through through the Codex in-app Browser/IAB runner instead of optional Python Playwright.")
    parser.add_argument("--browser-upload-photo", action="store_true")
    parser.add_argument("--browser-upload-pdf", action="store_true")
    parser.add_argument("--browser-upload-supporting-attachment", action="store_true", help="With browser click-through, upload a disposable synthetic declaration through the Supporting proof UI.")
    parser.add_argument("--browser-correction-mode", action="store_true")
    parser.add_argument("--browser-profile-proposal", action="store_true", help="With Browser/IAB click-through, preview a synthetic unknown recurring pattern as a proposed service profile without saving.")
    parser.add_argument("--browser-gmail-api-create", action="store_true", help="With Browser/IAB click-through, use fake Gmail mode to create and read-only verify a synthetic draft in the isolated runtime.")
    parser.add_argument("--browser-manual-handoff-stale", action="store_true", help="With Browser/IAB click-through and replacement/packet prepare, verify Manual Draft Handoff stale gates without recording drafts or calling Gmail.")
    parser.add_argument("--browser-recent-work-lifecycle", action="store_true", help="With Browser/IAB click-through, verify seeded Recent Work lifecycle controls without Gmail verify or local status writes.")
    parser.add_argument("--browser-prepare-replacement", action="store_true", help="With browser correction mode, prepare a replacement against a seeded synthetic active draft.")
    parser.add_argument("--browser-prepare-packet", action="store_true")
    parser.add_argument("--browser-record-helper", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_isolated_app_smoke(
        runtime_root=args.runtime_root,
        keep_runtime=args.keep_runtime,
        host=args.host,
        port=args.port,
        interaction_checks=args.interaction_checks,
        source_upload_checks=args.source_upload_checks,
        supporting_attachment_checks=args.supporting_attachment_checks,
        gmail_api_checks=args.gmail_api_checks,
        browser_click_through=args.browser_click_through,
        browser_iab_click_through=args.browser_iab_click_through,
        browser_upload_photo=args.browser_upload_photo,
        browser_upload_pdf=args.browser_upload_pdf,
        browser_upload_supporting_attachment=args.browser_upload_supporting_attachment,
        browser_correction_mode=args.browser_correction_mode,
        browser_profile_proposal=args.browser_profile_proposal,
        browser_gmail_api_create=args.browser_gmail_api_create,
        browser_manual_handoff_stale=args.browser_manual_handoff_stale,
        browser_recent_work_lifecycle=args.browser_recent_work_lifecycle,
        browser_prepare_replacement=args.browser_prepare_replacement,
        browser_prepare_packet=args.browser_prepare_packet,
        browser_record_helper=args.browser_record_helper,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Isolated app smoke: {report['status']} ({report['failure_count']} blockers)")
        isolated = report.get("isolated_runtime", {})
        print(f"Runtime: {isolated.get('runtime_root')}")
        print(f"Base URL: {isolated.get('base_url')}")
        for check in report.get("checks", []):
            marker = "OK" if check.get("status") == "ready" else "BLOCKED"
            print(f"[{marker}] {check.get('name')}: {check.get('message')}")
    return 0 if report.get("status") == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
