from __future__ import annotations

import argparse
import json
import sys
import tempfile
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

    def set_input_file(self, selector: str, path: str | Path) -> None:
        self._page.locator(selector).set_input_files(str(path), timeout=self.timeout_ms)

    def click(self, selector: str) -> None:
        self._page.locator(selector).click(timeout=self.timeout_ms)

    def expect_selector_visible(self, selector: str) -> None:
        self._page.locator(selector).wait_for(state="visible", timeout=self.timeout_ms)

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


_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
    b"\x00\x05\xfe\x02\xfeA\xde\xfc\x97\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_synthetic_photo(temp_dir: Path) -> Path:
    path = temp_dir / "synthetic-honorarios-photo.png"
    path.write_bytes(_TINY_PNG)
    return path


def _make_synthetic_pdf(temp_dir: Path, *, case_number: str, service_date: str) -> Path:
    path = temp_dir / "synthetic-honorarios-notification.pdf"
    year, month, day = service_date.split("-")
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception:
        path.write_bytes(
            b"%PDF-1.4\n"
            b"1 0 obj<<>>endobj\n"
            b"2 0 obj<< /Length 130 >>stream\n"
            b"BT /F1 12 Tf 72 760 Td (NUIPC: 999/26.0SMOKE) Tj 0 -18 Td "
            b"(Data da diligencia: 04/05/2026) Tj 0 -18 Td (Local: Posto da GNR de Exemplo) Tj ET\n"
            b"endstream endobj\n"
            b"3 0 obj<< /Type /Page /Parent 4 0 R /Contents 2 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
            b"4 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
            b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n"
            b"6 0 obj<< /Type /Catalog /Pages 4 0 R >>endobj\n"
            b"xref\n0 7\n0000000000 65535 f \ntrailer<< /Root 6 0 R /Size 7 >>\nstartxref\n0\n%%EOF\n"
        )
        return path

    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.drawString(72, 780, "AUTO DE INQUIRICAO")
    pdf.drawString(72, 760, f"NUIPC: {case_number}")
    pdf.drawString(72, 740, f"Data da diligencia: {day}/{month}/{year}")
    pdf.drawString(72, 720, "Local: Posto da GNR de Exemplo")
    pdf.drawString(72, 700, "Interprete: Example Interpreter")
    pdf.save()
    return path


def run_browser_flow_smoke(
    driver: Any | None = None,
    base_url: str = "http://127.0.0.1:8766",
    *,
    profile: str = DEFAULT_PROFILE,
    case_number: str = DEFAULT_CASE_NUMBER,
    service_date: str = DEFAULT_SERVICE_DATE,
    upload_photo: bool = False,
    upload_pdf: bool = False,
    answer_questions: bool = False,
    photo_upload_path: str | Path | None = None,
    pdf_upload_path: str | Path | None = None,
    correction_mode: bool = False,
    correction_reason: str = "synthetic correction smoke check",
    prepare_replacement: bool = False,
    prepare_packet: bool = False,
    record_helper: bool = False,
    headless: bool = True,
    timeout_ms: int = 10000,
) -> dict[str, Any]:
    base = _normalize_base_url(base_url)
    checks: list[dict[str, Any]] = []
    owns_driver = driver is None
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
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
        if (upload_photo and not photo_upload_path) or (upload_pdf and not pdf_upload_path):
            temp_dir = tempfile.TemporaryDirectory(prefix="honorarios-browser-smoke-")
            temp_path = Path(temp_dir.name)
            if upload_photo and not photo_upload_path:
                photo_upload_path = _make_synthetic_photo(temp_path)
            if upload_pdf and not pdf_upload_path:
                pdf_upload_path = _make_synthetic_pdf(temp_path, case_number=case_number, service_date=service_date)

        forbidden = FORBIDDEN_PREPARE_POSTS if (prepare_packet or prepare_replacement) else FORBIDDEN_DEFAULT_POSTS
        if hasattr(driver, "forbid_requests"):
            driver.forbid_requests(forbidden)

        if not _safe_step(checks, "browser_homepage", "Browser loaded the app shell.", lambda: (
            driver.goto(base + "/"),
            driver.expect_text("Start Interpretation Request"),
            driver.expect_text("Review Case Details"),
            driver.expect_text("Next Safe Action"),
            driver.expect_text("Draft-only Gmail"),
        )):
            return _report(base, checks)

        def _review_drawer() -> None:
            driver.select("#profile", profile)
            driver.fill("#case_number", case_number)
            driver.fill("#service_date", "" if answer_questions else service_date)
            driver.click("#review-intake")
            driver.expect_selector_text("#drawer-next-safe-action", "Next Safe Action")
            if answer_questions:
                driver.expect_text("Answer the numbered questions")
                driver.expect_selector_visible("#numbered-answers")
                driver.expect_text("Apply numbered answers")
            else:
                driver.expect_selector_text("#draft-text", "Número de processo")
                driver.expect_selector_text("#recipient-summary", "To:")

        if not _safe_step(checks, "browser_review_drawer", "Browser opened review drawer with Portuguese draft text.", _review_drawer):
            return _report(base, checks)

        if answer_questions:
            if not _safe_step(checks, "browser_answer_questions", "Browser applied numbered missing-info answers and reran review without preparing artifacts.", lambda: (
                driver.fill("#numbered-answers", f"1. {service_date}"),
                driver.click("#apply-numbered-answers"),
                driver.expect_selector_value("#service_date", service_date),
                driver.expect_selector_text("#draft-text", "Número de processo"),
                driver.expect_selector_text("#recipient-summary", "To:"),
            )):
                return _report(base, checks)

        if upload_photo:
            if not photo_upload_path:
                checks.append(_check("browser_photo_upload_evidence", False, "Photo upload smoke requires an upload path."))
                return _report(base, checks)
            if not _safe_step(checks, "browser_photo_upload_evidence", "Browser uploaded a synthetic photo and showed source evidence without preparing artifacts.", lambda: (
                driver.set_input_file("#photo-file", photo_upload_path),
                driver.click("#photo-upload-form button[type=submit]"),
                driver.expect_selector_visible("#source-evidence"),
                driver.expect_selector_text("#source-evidence-body", "Filename"),
            )):
                return _report(base, checks)

        if upload_pdf:
            if not pdf_upload_path:
                checks.append(_check("browser_pdf_upload_evidence", False, "PDF upload smoke requires an upload path."))
                return _report(base, checks)
            if not _safe_step(checks, "browser_pdf_upload_evidence", "Browser uploaded a synthetic notification PDF and surfaced candidate review fields without preparing artifacts.", lambda: (
                driver.set_input_file("#notification-file", pdf_upload_path),
                driver.click("#notification-upload-form button[type=submit]"),
                driver.expect_selector_visible("#source-evidence"),
                driver.expect_selector_text("#source-evidence-body", "Filename"),
                driver.expect_selector_value("#case_number", case_number),
                driver.expect_selector_value("#service_date", service_date),
            )):
                return _report(base, checks)

        if not _safe_step(checks, "browser_batch_queue", "Browser added the reviewed request to the batch queue without preparing artifacts.", lambda: (
            driver.click("#add-current-to-batch"),
            driver.expect_selector_text("#batch-count-chip", "1 queued"),
            driver.expect_text("Packet item inspector"),
        )):
            return _report(base, checks)

        if correction_mode:
            if not _safe_step(checks, "browser_correction_mode", "Browser checked draft lifecycle and filled a correction reason without preparing a replacement.", lambda: (
                driver.expect_text("Correction mode"),
                driver.click("#check-active-drafts"),
                driver.expect_selector_visible("#draft-lifecycle-panel"),
                driver.expect_selector_text("#draft-lifecycle-body", "draft"),
                driver.fill("#correction_reason", correction_reason),
                driver.expect_selector_value("#correction_reason", correction_reason),
            )):
                return _report(base, checks)

        if prepare_replacement:
            if not correction_mode:
                checks.append(_check(
                    "browser_replacement_prepare",
                    False,
                    "Replacement preparation smoke requires --correction-mode so a correction reason is present.",
                ))
                return _report(base, checks)
            if not _safe_step(checks, "browser_replacement_prepare", "Browser prepared a replacement payload without recording a draft or calling Gmail.", lambda: (
                driver.click("#prepare-replacement-draft"),
                driver.expect_text("Replacement payload prepared"),
                driver.expect_selector_visible("#prepare-results"),
                driver.expect_text("Draft-only Gmail"),
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
        if temp_dir is not None:
            temp_dir.cleanup()
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
    parser.add_argument("--upload-photo", action="store_true", help="Upload a disposable synthetic photo and verify source evidence. Does not click prepare or record.")
    parser.add_argument("--upload-pdf", action="store_true", help="Upload a disposable synthetic notification PDF and verify recovered review fields. Does not click prepare or record.")
    parser.add_argument("--answer-questions", action="store_true", help="Intentionally leave a required field blank, apply compact numbered answers, and rerun review without preparing artifacts.")
    parser.add_argument("--photo-upload-path", type=Path, default=None, help="Optional explicit local photo path for --upload-photo.")
    parser.add_argument("--pdf-upload-path", type=Path, default=None, help="Optional explicit local PDF path for --upload-pdf.")
    parser.add_argument("--correction-mode", action="store_true", help="Check the draft lifecycle/correction UI without preparing a replacement draft.")
    parser.add_argument("--correction-reason", default="synthetic correction smoke check")
    parser.add_argument("--prepare-replacement", action="store_true", help="With --correction-mode, click replacement prepare. This can create local PDF/payload artifacts but still blocks record/status writes.")
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
        upload_photo=args.upload_photo,
        upload_pdf=args.upload_pdf,
        answer_questions=args.answer_questions,
        photo_upload_path=args.photo_upload_path,
        pdf_upload_path=args.pdf_upload_path,
        correction_mode=args.correction_mode,
        correction_reason=args.correction_reason,
        prepare_replacement=args.prepare_replacement,
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
