from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any


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


def run_smoke(
    base_url: str = "http://127.0.0.1:8766",
    *,
    timeout: float = 5.0,
    fetch_text: Callable[[str], str] | None = None,
    fetch_json: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    base = _normalize_base_url(base_url)
    text_fetcher = fetch_text or (lambda url: _http_text(url, timeout))
    json_fetcher = fetch_json or (lambda url: _http_json(url, timeout))
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
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_smoke(args.base_url, timeout=args.timeout)
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
