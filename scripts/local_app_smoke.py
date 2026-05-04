from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any


TextFetcher = Callable[[str], str]
JsonFetcher = Callable[[str], Any]
PostJsonFetcher = Callable[[str, dict[str, Any]], Any]
BrowserRunner = Callable[..., dict[str, Any]]

LANDMARKS = [
    "LegalPDF Honorários",
    "Start Interpretation Request",
    "Review Case Details",
    "Review Interpretation Request",
    "Google Photos selected-photo import",
    "Open Google Photos Picker",
    "Batch Queue",
    "Packet mode",
    "Packet draft recording helper",
    "LegalPDF Integration Preview",
    "Build adapter import plan",
    "Draft-only Gmail",
]
FORBIDDEN_HOMEPAGE_COPY = ["_send_email", "_send_draft", "Send email", "Send draft"]
JSON_ENDPOINTS = [
    "/api/reference",
    "/api/google-photos/status",
    "/api/ai/status",
    "/api/public-readiness",
]


def _normalize_base_url(base_url: str) -> str:
    value = str(base_url or "").strip()
    if not value:
        raise ValueError("base_url is required")
    if not urllib.parse.urlparse(value).scheme:
        value = f"http://{value}"
    return value.rstrip("/")


def _url(base_url: str, path: str) -> str:
    return f"{base_url}{path}"


def _http_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _http_json(url: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _http_post_json(url: str, payload: dict[str, Any], timeout: float) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _check(name: str, passed: bool, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "ready" if passed else "blocked",
        "message": message,
        "details": details or {},
    }


def _send_allowed_values(value: Any, path: str = "$") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "send_allowed":
                found.append({"path": child_path, "value": child})
            found.extend(_send_allowed_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_send_allowed_values(child, f"{path}[{index}]"))
    return found


def _send_allowed_check(name: str, payload: Any, success_message: str) -> dict[str, Any]:
    send_values = _send_allowed_values(payload)
    non_false = [item for item in send_values if item["value"] is not False]
    return _check(
        name,
        not non_false,
        success_message if not non_false else "Response exposes a non-false send_allowed value.",
        {"non_false_send_allowed": non_false, "send_allowed_paths": send_values},
    )


def _post_workflow_json(
    post_json: PostJsonFetcher,
    url: str,
    payload: dict[str, Any],
    check_name: str,
) -> tuple[Any | None, dict[str, Any] | None]:
    try:
        return post_json(url, payload), None
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return None, _check(check_name, False, f"Could not call {url}: {exc}")


def _workflow_prepare_payload_ready(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    items = payload.get("items")
    first_item = items[0] if isinstance(items, list) and items else {}
    item_args = first_item.get("gmail_create_draft_args") if isinstance(first_item, dict) else {}
    item_attachments = item_args.get("attachment_files") if isinstance(item_args, dict) else None
    packet = payload.get("packet") if isinstance(payload.get("packet"), dict) else {}
    packet_args = packet.get("gmail_create_draft_args") if isinstance(packet.get("gmail_create_draft_args"), dict) else {}
    packet_attachments = packet_args.get("attachment_files") if isinstance(packet_args, dict) else None
    underlying = packet.get("underlying_requests")
    details = {
        "status": payload.get("status"),
        "packet_mode": payload.get("packet_mode"),
        "item_attachment_count": len(item_attachments) if isinstance(item_attachments, list) else None,
        "packet_attachment_count": len(packet_attachments) if isinstance(packet_attachments, list) else None,
        "underlying_request_count": len(underlying) if isinstance(underlying, list) else None,
    }
    ready = (
        isinstance(payload, dict)
        and payload.get("status") == "prepared"
        and payload.get("send_allowed") is False
        and isinstance(items, list)
        and bool(items)
        and isinstance(item_attachments, list)
        and first_item.get("gmail_create_draft_ready") is not False
        and isinstance(packet, dict)
        and packet.get("gmail_create_draft_ready") is not False
        and isinstance(packet_attachments, list)
        and isinstance(underlying, list)
        and bool(underlying)
    )
    return ready, details


def _run_interaction_checks(
    base: str,
    *,
    post_json: PostJsonFetcher,
    profile: str,
    case_number: str,
    service_date: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    intake_payload = {
        "profile": profile,
        "case_number": case_number,
        "service_date": service_date,
    }
    intake_response, error_check = _post_workflow_json(
        post_json,
        _url(base, "/api/intake/from-profile"),
        intake_payload,
        "workflow_build_intake",
    )
    if error_check:
        return [error_check]
    checks.append(_send_allowed_check(
        "workflow_build_intake_send_allowed",
        intake_response,
        "Profile intake creation keeps send_allowed false.",
    ))
    review = intake_response.get("review") if isinstance(intake_response, dict) else {}
    intake = intake_response.get("intake") if isinstance(intake_response, dict) else None
    draft_text = str(review.get("draft_text") or "") if isinstance(review, dict) else ""
    intake_ready = (
        isinstance(intake_response, dict)
        and intake_response.get("status") == "created"
        and isinstance(intake, dict)
        and isinstance(review, dict)
        and review.get("status") == "ready"
        and bool(draft_text.strip())
        and ("Número de processo" in draft_text or "Numero de processo" in draft_text)
    )
    checks.append(_check(
        "workflow_build_intake",
        intake_ready,
        "Profile intake produces a ready review and Portuguese draft text." if intake_ready else "Profile intake did not produce a ready review.",
        {"status": intake_response.get("status") if isinstance(intake_response, dict) else None},
    ))
    if not intake_ready or not isinstance(intake, dict):
        return checks

    lifecycle_response, error_check = _post_workflow_json(
        post_json,
        _url(base, "/api/drafts/active-check"),
        {"intake": intake},
        "workflow_active_draft_check",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "workflow_active_draft_check_send_allowed",
        lifecycle_response,
        "Active-draft check keeps send_allowed false.",
    ))
    lifecycle_status = lifecycle_response.get("status") if isinstance(lifecycle_response, dict) else None
    lifecycle_ready = lifecycle_status in {"clear", "ready"}
    checks.append(_check(
        "workflow_active_draft_check",
        lifecycle_ready,
        "Active-draft check is clear for the synthetic request." if lifecycle_ready else "Active-draft check blocked the synthetic request.",
        {"status": lifecycle_status},
    ))
    if not lifecycle_ready:
        return checks

    prepare_response, error_check = _post_workflow_json(
        post_json,
        _url(base, "/api/prepare"),
        {"intakes": [intake], "render_previews": False, "packet_mode": True},
        "workflow_prepare_packet_payload",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "workflow_prepare_packet_payload_send_allowed",
        prepare_response,
        "Prepare response keeps send_allowed false.",
    ))
    packet_ready = False
    details: dict[str, Any] = {}
    if isinstance(prepare_response, dict):
        packet_ready, details = _workflow_prepare_payload_ready(prepare_response)
    checks.append(_check(
        "workflow_prepare_packet_payload",
        packet_ready,
        "Packet prepare result exposes draft-only Gmail args with attachment arrays and underlying requests." if packet_ready else "Packet prepare result is missing its draft-only packet contract.",
        details,
    ))
    return checks


def run_smoke(
    base_url: str = "http://127.0.0.1:8766",
    *,
    timeout: float = 5.0,
    fetch_text: TextFetcher | None = None,
    fetch_json: JsonFetcher | None = None,
    post_json: PostJsonFetcher | None = None,
    interaction_checks: bool = False,
    interaction_profile: str = "example_interpreting",
    interaction_case_number: str = "999/26.0SMOKE",
    interaction_service_date: str = "2026-05-04",
    browser_click_through: bool = False,
    browser_prepare_packet: bool = False,
    browser_record_helper: bool = False,
    browser_runner: BrowserRunner | None = None,
) -> dict[str, Any]:
    base = _normalize_base_url(base_url)
    text_fetcher = fetch_text or (lambda url: _http_text(url, timeout))
    json_fetcher = fetch_json or (lambda url: _http_json(url, timeout))
    json_poster = post_json or (lambda url, payload: _http_post_json(url, payload, timeout))
    checks: list[dict[str, Any]] = []
    endpoint_payloads: dict[str, Any] = {}

    try:
        homepage = text_fetcher(_url(base, "/"))
    except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
        homepage = ""
        checks.append(_check("homepage_reachable", False, f"Could not load homepage: {exc}"))
    else:
        checks.append(_check("homepage_reachable", True, "Homepage loaded."))
        missing = [text for text in LANDMARKS if text not in homepage]
        checks.append(_check(
            "homepage_landmarks",
            not missing,
            "Homepage includes the LegalPDF-style honorários workflow landmarks." if not missing else "Homepage is missing expected workflow landmarks.",
            {"missing": missing},
        ))
        forbidden = [text for text in FORBIDDEN_HOMEPAGE_COPY if text in homepage]
        checks.append(_check(
            "homepage_forbidden_send_copy",
            not forbidden,
            "Homepage does not expose forbidden send-capable Gmail copy." if not forbidden else "Homepage exposes send-capable Gmail copy.",
            {"forbidden": forbidden},
        ))

    for path in JSON_ENDPOINTS:
        name = f"endpoint_{path.strip('/').replace('/', '_').replace('-', '_')}"
        try:
            payload = json_fetcher(_url(base, path))
        except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            checks.append(_check(name, False, f"Could not load {path}: {exc}"))
            continue
        endpoint_payloads[path] = payload
        send_values = _send_allowed_values(payload)
        non_false = [item for item in send_values if item["value"] is not False]
        checks.append(_check(
            name,
            not non_false,
            f"{path} keeps send_allowed false wherever it appears." if not non_false else f"{path} exposes a non-false send_allowed value.",
            {"non_false_send_allowed": non_false, "send_allowed_paths": send_values},
        ))

    reference = endpoint_payloads.get("/api/reference")
    if isinstance(reference, dict):
        gmail = reference.get("gmail") if isinstance(reference.get("gmail"), dict) else {}
        checks.append(_check(
            "reference_gmail_tool",
            gmail.get("tool") == "_create_draft" and gmail.get("send_allowed") is False,
            "/api/reference exposes _create_draft as draft-only Gmail handoff.",
            {"gmail": gmail},
        ))

    google_status = endpoint_payloads.get("/api/google-photos/status")
    if isinstance(google_status, dict):
        secret_keys = {"client_secret", "access_token", "refresh_token", "media_base_url", "photo_url", "selected_media_id"}
        exposed = sorted(secret_keys.intersection(google_status.keys()))
        checks.append(_check(
            "google_photos_status_secret_free",
            not exposed,
            "/api/google-photos/status does not expose token, URL, or media-id secrets.",
            {"exposed": exposed},
        ))

    if interaction_checks:
        checks.extend(_run_interaction_checks(
            base,
            post_json=json_poster,
            profile=interaction_profile,
            case_number=interaction_case_number,
            service_date=interaction_service_date,
        ))

    if browser_click_through:
        if browser_runner is None:
            try:
                from scripts.browser_flow_smoke import run_browser_flow_smoke
            except Exception as exc:
                browser_report = {
                    "status": "blocked",
                    "checks": [_check("browser_driver_available", False, f"Could not load browser flow smoke runner: {exc}")],
                    "failure_count": 1,
                    "send_allowed": False,
                }
            else:
                browser_report = run_browser_flow_smoke(
                    base_url=base,
                    profile=interaction_profile,
                    case_number=interaction_case_number,
                    service_date=interaction_service_date,
                    prepare_packet=browser_prepare_packet,
                    record_helper=browser_record_helper,
                )
        else:
            browser_report = browser_runner(
                base,
                profile=interaction_profile,
                case_number=interaction_case_number,
                service_date=interaction_service_date,
                prepare_packet=browser_prepare_packet,
                record_helper=browser_record_helper,
            )
        checks.extend(browser_report.get("checks", []) if isinstance(browser_report, dict) else [])
        checks.append(_send_allowed_check(
            "browser_click_through_send_allowed",
            browser_report,
            "Browser click-through report keeps send_allowed false.",
        ))

    failure_count = sum(1 for check in checks if check["status"] != "ready")
    return {
        "status": "ready" if failure_count == 0 else "blocked",
        "base_url": base,
        "checks": checks,
        "failure_count": failure_count,
        "send_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check the live local Honorários browser app.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8766")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--interaction-checks", action="store_true", help="Also exercise the opt-in profile/review/packet-prepare contract. This may create local draft payload/PDF artifacts on a real app.")
    parser.add_argument("--interaction-profile", default="example_interpreting")
    parser.add_argument("--interaction-case-number", default="999/26.0SMOKE")
    parser.add_argument("--interaction-service-date", default="2026-05-04")
    parser.add_argument("--browser-click-through", action="store_true", help="Opt-in real browser review-flow click-through. Does not click prepare or record drafts unless the explicit browser prepare flags are used.")
    parser.add_argument("--browser-prepare-packet", action="store_true", help="With --browser-click-through, also click packet prepare. This can create local PDF/payload artifacts.")
    parser.add_argument("--browser-record-helper", action="store_true", help="With --browser-click-through and packet prepare, parse fake Gmail IDs and autofill record fields without recording.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_smoke(
        args.base_url,
        timeout=args.timeout,
        interaction_checks=args.interaction_checks,
        interaction_profile=args.interaction_profile,
        interaction_case_number=args.interaction_case_number,
        interaction_service_date=args.interaction_service_date,
        browser_click_through=args.browser_click_through,
        browser_prepare_packet=args.browser_prepare_packet,
        browser_record_helper=args.browser_record_helper,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Local app smoke: {report['status']} ({report['failure_count']} blockers)")
        for check in report["checks"]:
            marker = "OK" if check["status"] == "ready" else "BLOCKED"
            print(f"[{marker}] {check['name']}: {check['message']}")
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
