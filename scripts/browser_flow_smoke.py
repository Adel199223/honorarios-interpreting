from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.local_app_smoke import _check, _normalize_base_url


DEFAULT_CASE_NUMBER = "999/26.0SMOKE"
DEFAULT_SERVICE_DATE = "2026-05-04"
DEFAULT_PROFILE = "example_interpreting"
FORBIDDEN_DEFAULT_POSTS = {"/api/prepare", "/api/drafts/record", "/api/drafts/status"}
FORBIDDEN_PREPARE_POSTS = {"/api/drafts/record", "/api/drafts/status"}


class PlaywrightBrowserDriver:
    def __init__(self, *, headless: bool = True, timeout_ms: int = 10000):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Python Playwright is not installed. Install the optional browser dependency or use an injected driver.") from exc
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=headless)
            self._page = self._browser.new_page()
        except Exception:
            self.close()
            raise
        self.timeout_ms = timeout_ms

    def close(self) -> None:
        browser = getattr(self, "_browser", None)
        playwright = getattr(self, "_playwright", None)
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()

    def forbid_requests(self, paths: set[str]) -> None:
        def _route(route):
            request = route.request
            if request.method.upper() == "POST" and any(request.url.endswith(path) for path in paths):
                raise RuntimeError(f"Forbidden browser smoke POST attempted: {request.method} {request.url}")
            route.continue_()

        self._page.route("**/*", _route)

    def goto(self, url: str) -> None:
        self._page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)

    def expect_text(self, text: str) -> None:
        self._page.get_by_text(text, exact=False).wait_for(state="visible", timeout=self.timeout_ms)

    def fill(self, selector: str, value: str) -> None:
        self._page.locator(selector).fill(value, timeout=self.timeout_ms)

    def select(self, selector: str, value: str) -> None:
        self._page.locator(selector).select_option(value, timeout=self.timeout_ms)

    def check(self, selector: str) -> None:
        self._page.locator(selector).check(timeout=self.timeout_ms)

    def click(self, selector: str) -> None:
        self._page.locator(selector).click(timeout=self.timeout_ms)

    def expect_selector_text(self, selector: str, text: str) -> None:
        locator = self._page.locator(selector)
        locator.wait_for(state="visible", timeout=self.timeout_ms)
        content = locator.inner_text(timeout=self.timeout_ms)
        if text not in content:
            raise RuntimeError(f"Expected {selector} to contain {text!r}; got {content!r}")

    def expect_selector_value(self, selector: str, value: str) -> None:
        locator = self._page.locator(selector)
        locator.wait_for(state="visible", timeout=self.timeout_ms)
        actual = locator.input_value(timeout=self.timeout_ms)
        if value not in actual:
            raise RuntimeError(f"Expected {selector} value to contain {value!r}; got {actual!r}")


def _safe_step(checks: list[dict[str, Any]], name: str, message: str, action) -> bool:
    try:
        action()
    except Exception as exc:
        checks.append(_check(name, False, str(exc)))
        return False
    checks.append(_check(name, True, message))
    return True


def run_browser_flow_smoke(
    driver: Any | None = None,
    base_url: str = "http://127.0.0.1:8766",
    *,
    profile: str = DEFAULT_PROFILE,
    case_number: str = DEFAULT_CASE_NUMBER,
    service_date: str = DEFAULT_SERVICE_DATE,
    prepare_packet: bool = False,
    record_helper: bool = False,
    headless: bool = True,
    timeout_ms: int = 10000,
) -> dict[str, Any]:
    base = _normalize_base_url(base_url)
    checks: list[dict[str, Any]] = []
    owns_driver = driver is None
    if driver is None:
        try:
            driver = PlaywrightBrowserDriver(headless=headless, timeout_ms=timeout_ms)
        except Exception as exc:
            checks.append(_check("browser_driver_available", False, str(exc)))
            return {
                "status": "blocked",
                "base_url": base,
                "checks": checks,
                "failure_count": 1,
                "send_allowed": False,
            }

    try:
        forbidden = FORBIDDEN_PREPARE_POSTS if prepare_packet else FORBIDDEN_DEFAULT_POSTS
        if hasattr(driver, "forbid_requests"):
            driver.forbid_requests(forbidden)

        if not _safe_step(checks, "browser_homepage", "Browser loaded the app shell.", lambda: (
            driver.goto(base + "/"),
            driver.expect_text("Start Interpretation Request"),
            driver.expect_text("Review Case Details"),
            driver.expect_text("Draft-only Gmail"),
        )):
            return _report(base, checks)

        if not _safe_step(checks, "browser_review_drawer", "Browser opened review drawer with Portuguese draft text.", lambda: (
            driver.select("#profile", profile),
            driver.fill("#case_number", case_number),
            driver.fill("#service_date", service_date),
            driver.click("#review-intake"),
            driver.expect_selector_text("#draft-text", "Número de processo"),
            driver.expect_selector_text("#recipient-summary", "To:"),
        )):
            return _report(base, checks)

        if not _safe_step(checks, "browser_batch_queue", "Browser added the reviewed request to the batch queue without preparing artifacts.", lambda: (
            driver.click("#add-current-to-batch"),
            driver.expect_selector_text("#batch-count-chip", "1 queued"),
            driver.expect_text("Packet item inspector"),
        )):
            return _report(base, checks)

        if prepare_packet:
            if not _safe_step(checks, "browser_packet_prepare", "Browser prepared packet mode and exposed packet draft helpers.", lambda: (
                driver.check("#batch-packet-mode"),
                driver.click("#prepare-batch-intakes"),
                driver.expect_text("Packet draft recording helper"),
                driver.expect_text("Underlying duplicate blockers"),
            )):
                return _report(base, checks)

        if record_helper:
            fake_response = '{"id":"draft-smoke","message":{"id":"message-smoke","threadId":"thread-smoke"}}'
            def _expect_record_id() -> None:
                if hasattr(driver, "expect_selector_value"):
                    driver.expect_selector_value("#record_draft_id", "draft-smoke")
                else:
                    driver.expect_selector_text("#record_draft_id", "draft-smoke")

            if not _safe_step(checks, "browser_record_helper", "Browser parsed Gmail IDs and autofilled the local record form without recording.", lambda: (
                driver.fill("#gmail-response-raw", fake_response),
                driver.click("#parse-gmail-response"),
                driver.click("#autofill-record-from-prepared"),
                _expect_record_id(),
            )):
                return _report(base, checks)
    finally:
        if owns_driver and hasattr(driver, "close"):
            driver.close()
    return _report(base, checks)


def _report(base: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    failure_count = sum(1 for check in checks if check["status"] != "ready")
    return {
        "status": "ready" if failure_count == 0 else "blocked",
        "base_url": base,
        "checks": checks,
        "failure_count": failure_count,
        "send_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in browser click-through smoke for the Honorários app.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8766")
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--case-number", default=DEFAULT_CASE_NUMBER)
    parser.add_argument("--service-date", default=DEFAULT_SERVICE_DATE)
    parser.add_argument("--prepare-packet", action="store_true", help="Also click packet prepare. This can create local PDF/payload artifacts.")
    parser.add_argument("--record-helper", action="store_true", help="After packet prepare, parse fake Gmail IDs and autofill record fields without recording.")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_browser_flow_smoke(
        base_url=args.base_url,
        profile=args.profile,
        case_number=args.case_number,
        service_date=args.service_date,
        prepare_packet=args.prepare_packet,
        record_helper=args.record_helper,
        headless=not args.headed,
        timeout_ms=args.timeout_ms,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Browser flow smoke: {report['status']} ({report['failure_count']} blockers)")
        for check in report["checks"]:
            marker = "OK" if check["status"] == "ready" else "BLOCKED"
            print(f"[{marker}] {check['name']}: {check['message']}")
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
