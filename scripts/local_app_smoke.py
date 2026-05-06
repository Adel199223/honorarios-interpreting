from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
import subprocess
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


TextFetcher = Callable[[str], str]
JsonFetcher = Callable[[str], Any]
PostJsonFetcher = Callable[[str, dict[str, Any]], Any]
PostMultipartFetcher = Callable[[str, dict[str, str], str, bytes, str], Any]
BrowserRunner = Callable[..., dict[str, Any]]

LANDMARKS = [
    "LegalPDF Honorários",
    "Start Interpretation Request",
    "Review Case Details",
    "Review Interpretation Request",
    "Next Safe Action",
    "Drop or paste a notification PDF, photo, or screenshot here",
    "Google Photos selected-photo import",
    "Open Google Photos Picker",
    "Batch Queue",
    "Packet mode",
    "Packet draft recording helper",
    "LegalPDF Integration Preview",
    "Build adapter import plan",
    "LegalPDF Apply History",
    "LegalPDF Restore Plan",
    "Refresh apply history",
    "Draft-only Gmail",
]
FORBIDDEN_HOMEPAGE_COPY = ["_send_email", "_send_draft", "Send email", "Send draft"]
JSON_ENDPOINTS = [
    "/api/reference",
    "/api/google-photos/status",
    "/api/ai/status",
    "/api/public-readiness",
    "/api/diagnostics/status",
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


def _http_post_multipart(
    url: str,
    fields: dict[str, str],
    filename: str,
    content: bytes,
    content_type: str,
    timeout: float,
) -> Any:
    boundary = f"----honorarios-smoke-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
            str(value).encode("utf-8"),
            b"\r\n",
        ])
    safe_filename = Path(filename).name.replace('"', "")
    chunks.extend([
        f"--{boundary}\r\n".encode("ascii"),
        f'Content-Disposition: form-data; name="file"; filename="{safe_filename}"\r\n'.encode("ascii"),
        f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode("ascii"),
    ])
    body = b"".join(chunks)
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
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


_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
    b"\x00\x05\xfe\x02\xfeA\xde\xfc\x97\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _synthetic_notification_pdf(case_number: str, service_date: str) -> bytes:
    try:
        from reportlab.pdfgen import canvas
    except Exception as exc:  # pragma: no cover - dependency is part of the app, but keep the smoke readable.
        raise RuntimeError(f"Cannot create synthetic PDF fixture because reportlab is unavailable: {exc}") from exc

    raw_case = f"000{case_number}" if not str(case_number).startswith("000") else str(case_number)
    day, month, year = service_date.split("-")[2], service_date.split("-")[1], service_date.split("-")[0]
    output = BytesIO()
    document = canvas.Canvas(output)
    document.drawString(72, 720, f"NUIPC {raw_case}")
    document.drawString(72, 700, f"Data/Hora da diligência: {day}/{month}/{year} 10:00")
    document.drawString(72, 680, "Local: Posto Territorial de Serpa")
    document.drawString(72, 660, "Email: court@example.test")
    document.save()
    return output.getvalue()


def _run_browser_iab_smoke_subprocess(base_url: str, **kwargs: Any) -> dict[str, Any]:
    script = Path(__file__).resolve().with_name("browser_iab_smoke.mjs")
    script_url = script.resolve().as_posix()
    node_repl_cell = (
        f"const {{ runBrowserIabSmoke }} = await import('file:///{script_url}?run=' + Date.now());\n"
        "const result = await runBrowserIabSmoke({\n"
        f"  baseUrl: {json.dumps(base_url)},\n"
        f"  profile: {json.dumps(str(kwargs.get('profile') or 'example_interpreting'))},\n"
        f"  caseNumber: {json.dumps(str(kwargs.get('case_number') or '999/26.0SMOKE'))},\n"
        f"  serviceDate: {json.dumps(str(kwargs.get('service_date') or '2026-05-04'))},\n"
        f"  uploadPhoto: {str(bool(kwargs.get('upload_photo'))).lower()},\n"
        f"  uploadPdf: {str(bool(kwargs.get('upload_pdf'))).lower()},\n"
        f"  answerQuestions: {str(bool(kwargs.get('answer_questions'))).lower()},\n"
        f"  correctionMode: {str(bool(kwargs.get('correction_mode'))).lower()},\n"
        f"  prepareReplacement: {str(bool(kwargs.get('prepare_replacement'))).lower()},\n"
        f"  preparePacket: {str(bool(kwargs.get('prepare_packet'))).lower()},\n"
        f"  recordHelper: {str(bool(kwargs.get('record_helper'))).lower()},\n"
        f"  applyHistory: {str(bool(kwargs.get('apply_history'))).lower()},\n"
        "  timeoutMs: 15000,\n"
        "});\n"
        "nodeRepl.write(JSON.stringify(result, null, 2));"
    )
    if os.environ.get("HONORARIOS_ALLOW_IAB_SUBPROCESS") != "1":
        return {
            "status": "blocked",
            "checks": [_check(
                "browser_iab_runtime",
                False,
                "Browser/IAB smoke must run through the Codex Node REPL Browser runtime; raw subprocess execution is intentionally skipped.",
                {"node_repl_cell": node_repl_cell, "script": str(script.resolve())},
            )],
            "failure_count": 1,
            "send_allowed": False,
        }
    cmd = [
        "node",
        str(script),
        "--base-url",
        base_url,
        "--profile",
        str(kwargs.get("profile") or "example_interpreting"),
        "--case-number",
        str(kwargs.get("case_number") or "999/26.0SMOKE"),
        "--service-date",
        str(kwargs.get("service_date") or "2026-05-04"),
        "--json",
    ]
    if kwargs.get("upload_photo"):
        cmd.append("--upload-photo")
    if kwargs.get("upload_pdf"):
        cmd.append("--upload-pdf")
    if kwargs.get("answer_questions"):
        cmd.append("--answer-questions")
    if kwargs.get("correction_mode"):
        cmd.append("--correction-mode")
    if kwargs.get("prepare_replacement"):
        cmd.append("--prepare-replacement")
    if kwargs.get("prepare_packet"):
        cmd.append("--prepare-packet")
    if kwargs.get("record_helper"):
        cmd.append("--record-helper")
    if kwargs.get("apply_history"):
        cmd.append("--apply-history")
    correction_reason = kwargs.get("correction_reason")
    if correction_reason:
        cmd.extend(["--correction-reason", str(correction_reason)])
    try:
        result = subprocess.run(cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=90)
    except Exception as exc:
        return {
            "status": "blocked",
            "checks": [_check("browser_iab_runtime", False, f"Could not start Browser/IAB smoke subprocess: {exc}")],
            "failure_count": 1,
            "send_allowed": False,
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "status": "blocked",
            "checks": [_check(
                "browser_iab_runtime",
                False,
                "Browser/IAB smoke did not return valid JSON.",
                {"returncode": result.returncode, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]},
            )],
            "failure_count": 1,
            "send_allowed": False,
        }
    if not isinstance(payload, dict):
        return {
            "status": "blocked",
            "checks": [_check("browser_iab_runtime", False, "Browser/IAB smoke returned a non-object payload.")],
            "failure_count": 1,
            "send_allowed": False,
        }
    if result.returncode != 0 and payload.get("failure_count") in (None, 0):
        payload.setdefault("checks", []).append(_check(
            "browser_iab_runtime_exit_code",
            False,
            "Browser/IAB smoke exited with a non-zero code.",
            {"returncode": result.returncode, "stderr": result.stderr[-2000:]},
        ))
        payload["status"] = "blocked"
        payload["failure_count"] = sum(1 for check in payload.get("checks", []) if check.get("status") != "ready")
    payload["send_allowed"] = False
    return payload


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

    preflight_response, error_check = _post_workflow_json(
        post_json,
        _url(base, "/api/prepare/preflight"),
        {"intakes": [intake], "packet_mode": True},
        "workflow_batch_preflight",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "workflow_batch_preflight_send_allowed",
        preflight_response,
        "Batch preflight keeps send_allowed false.",
    ))
    preflight_ready = (
        isinstance(preflight_response, dict)
        and preflight_response.get("status") == "ready"
        and preflight_response.get("artifact_effect") == "none"
        and preflight_response.get("write_allowed") is False
    )
    checks.append(_check(
        "workflow_batch_preflight",
        preflight_ready,
        "Batch preflight validates queued requests without creating artifacts." if preflight_ready else "Batch preflight did not return the non-writing ready contract.",
        {
            "status": preflight_response.get("status") if isinstance(preflight_response, dict) else None,
            "artifact_effect": preflight_response.get("artifact_effect") if isinstance(preflight_response, dict) else None,
            "write_allowed": preflight_response.get("write_allowed") if isinstance(preflight_response, dict) else None,
        },
    ))
    if not preflight_ready:
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


def _attention_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    evidence = payload.get("source_evidence") if isinstance(payload.get("source_evidence"), dict) else {}
    attention = evidence.get("attention") if isinstance(evidence.get("attention"), dict) else {}
    flags = attention.get("flags") if isinstance(attention.get("flags"), list) else []
    return {
        "status": attention.get("status"),
        "flag_count": attention.get("flag_count"),
        "codes": [flag.get("code") for flag in flags if isinstance(flag, dict)],
    }


def _upload_response_has_attention(payload: Any) -> bool:
    summary = _attention_summary(payload)
    return summary.get("status") in {"ready", "review", "blocked"} and isinstance(summary.get("flag_count"), int)


def _run_source_upload_checks(
    base: str,
    *,
    post_multipart: PostMultipartFetcher,
    case_number: str,
    service_date: str,
    profile: str = "",
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    photo_payload = {
        "source_kind": "photo",
        "profile": profile,
        "visible_metadata_text": f"Filename: {service_date.replace('-', '')}_100000.jpg\nDate: {service_date}",
    }
    try:
        photo_response = post_multipart(
            _url(base, "/api/sources/upload"),
            photo_payload,
            f"{service_date.replace('-', '')}_100000.jpg",
            _TINY_PNG,
            "image/png",
        )
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        checks.append(_check("source_upload_photo_attention", False, f"Could not upload synthetic photo source: {exc}"))
    else:
        checks.append(_send_allowed_check(
            "source_upload_photo_send_allowed",
            photo_response,
            "Synthetic photo upload keeps send_allowed false.",
        ))
        attention_ready = (
            isinstance(photo_response, dict)
            and photo_response.get("status") == "uploaded"
            and _upload_response_has_attention(photo_response)
        )
        checks.append(_check(
            "source_upload_photo_attention",
            attention_ready,
            "Synthetic photo upload returns Source Evidence with Review Attention." if attention_ready else "Synthetic photo upload did not return Source Evidence attention.",
            _attention_summary(photo_response),
        ))

    pdf_bytes = _synthetic_notification_pdf(case_number, service_date)
    pdf_payload = {
        "source_kind": "notification_pdf",
        "profile": profile,
        "visible_metadata_text": "",
    }
    try:
        pdf_response = post_multipart(
            _url(base, "/api/sources/upload"),
            pdf_payload,
            "synthetic-notification.pdf",
            pdf_bytes,
            "application/pdf",
        )
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        checks.append(_check("source_upload_pdf_evidence", False, f"Could not upload synthetic PDF source: {exc}"))
    else:
        checks.append(_send_allowed_check(
            "source_upload_pdf_send_allowed",
            pdf_response,
            "Synthetic PDF upload keeps send_allowed false.",
        ))
        candidate = pdf_response.get("candidate_intake") if isinstance(pdf_response, dict) else {}
        pdf_ready = (
            isinstance(pdf_response, dict)
            and pdf_response.get("status") == "uploaded"
            and isinstance(candidate, dict)
            and candidate.get("case_number") == case_number
            and candidate.get("service_date") == service_date
            and _upload_response_has_attention(pdf_response)
        )
        details = {
            "case_number": candidate.get("case_number") if isinstance(candidate, dict) else None,
            "service_date": candidate.get("service_date") if isinstance(candidate, dict) else None,
            "attention": _attention_summary(pdf_response),
        }
        checks.append(_check(
            "source_upload_pdf_evidence",
            pdf_ready,
            "Synthetic PDF upload recovers candidate fields and Review Attention without preparing artifacts." if pdf_ready else "Synthetic PDF upload did not recover the expected candidate evidence.",
            details,
        ))

    return checks


def _run_supporting_attachment_checks(
    base: str,
    *,
    post_multipart: PostMultipartFetcher,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    pdf_bytes = _synthetic_notification_pdf("999/26.0SMOKE", "2026-05-04")
    try:
        response = post_multipart(
            _url(base, "/api/attachments/upload"),
            {},
            "synthetic-declaracao.pdf",
            pdf_bytes,
            "application/pdf",
        )
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        checks.append(_check("supporting_attachment_upload_evidence", False, f"Could not upload synthetic supporting attachment: {exc}"))
        return checks

    checks.append(_send_allowed_check(
        "supporting_attachment_upload_send_allowed",
        response,
        "Synthetic supporting attachment upload keeps send_allowed false.",
    ))
    attachment = response.get("attachment") if isinstance(response, dict) else {}
    forbidden_artifacts = [
        key for key in ("candidate_intake", "review", "draft_payload", "gmail_create_draft_args", "pdf", "manifest")
        if isinstance(response, dict) and key in response
    ]
    ready = (
        isinstance(response, dict)
        and response.get("status") == "uploaded"
        and isinstance(attachment, dict)
        and attachment.get("source_kind") == "supporting_attachment"
        and attachment.get("attachment_kind") in {"notification_pdf", "photo"}
        and str(attachment.get("artifact_url") or "").startswith("/api/artifacts/sources/")
        and not forbidden_artifacts
    )
    checks.append(_check(
        "supporting_attachment_upload_evidence",
        ready,
        "Synthetic supporting attachment upload returns safe attachment evidence only." if ready else "Synthetic supporting attachment upload returned unsafe or incomplete evidence.",
        {
            "status": response.get("status") if isinstance(response, dict) else None,
            "source_kind": attachment.get("source_kind") if isinstance(attachment, dict) else None,
            "attachment_kind": attachment.get("attachment_kind") if isinstance(attachment, dict) else None,
            "artifact_url": attachment.get("artifact_url") if isinstance(attachment, dict) else None,
            "forbidden_artifacts": forbidden_artifacts,
        },
    ))
    return checks


def run_smoke(
    base_url: str = "http://127.0.0.1:8766",
    *,
    timeout: float = 5.0,
    fetch_text: TextFetcher | None = None,
    fetch_json: JsonFetcher | None = None,
    post_json: PostJsonFetcher | None = None,
    post_multipart: PostMultipartFetcher | None = None,
    interaction_checks: bool = False,
    source_upload_checks: bool = False,
    supporting_attachment_checks: bool = False,
    source_upload_profile: str = "",
    interaction_profile: str = "example_interpreting",
    interaction_case_number: str = "999/26.0SMOKE",
    interaction_service_date: str = "2026-05-04",
    browser_click_through: bool = False,
    browser_prepare_packet: bool = False,
    browser_prepare_replacement: bool = False,
    browser_record_helper: bool = False,
    browser_upload_photo: bool = False,
    browser_upload_pdf: bool = False,
    browser_answer_questions: bool = False,
    browser_correction_mode: bool = False,
    browser_apply_history: bool = False,
    browser_iab_click_through: bool = False,
    browser_runner: BrowserRunner | None = None,
) -> dict[str, Any]:
    base = _normalize_base_url(base_url)
    text_fetcher = fetch_text or (lambda url: _http_text(url, timeout))
    json_fetcher = fetch_json or (lambda url: _http_json(url, timeout))
    json_poster = post_json or (lambda url, payload: _http_post_json(url, payload, timeout))
    multipart_poster = post_multipart or (lambda url, fields, filename, content, content_type: _http_post_multipart(url, fields, filename, content, content_type, timeout))
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

    diagnostics = endpoint_payloads.get("/api/diagnostics/status")
    if isinstance(diagnostics, dict) and "checks" in diagnostics:
        diagnostic_checks = diagnostics.get("checks") if isinstance(diagnostics.get("checks"), list) else []
        check_keys = {item.get("key") for item in diagnostic_checks if isinstance(item, dict)}
        required_keys = {
            "default_live_smoke",
            "source_upload_smoke",
            "supporting_attachment_smoke",
            "browser_iab_upload_smoke",
        }
        missing = sorted(required_keys.difference(check_keys))
        checks.append(_check(
            "diagnostics_safe_smoke_commands",
            not missing and diagnostics.get("write_allowed") is False,
            "/api/diagnostics/status lists safe local smoke commands without enabling writes." if not missing else "Diagnostics status is missing expected smoke commands.",
            {"missing": missing, "write_allowed": diagnostics.get("write_allowed")},
        ))

    if interaction_checks:
        checks.extend(_run_interaction_checks(
            base,
            post_json=json_poster,
            profile=interaction_profile,
            case_number=interaction_case_number,
            service_date=interaction_service_date,
        ))

    if source_upload_checks:
        checks.extend(_run_source_upload_checks(
            base,
            post_multipart=multipart_poster,
            case_number=interaction_case_number,
            service_date=interaction_service_date,
            profile=source_upload_profile,
        ))

    if supporting_attachment_checks:
        checks.extend(_run_supporting_attachment_checks(
            base,
            post_multipart=multipart_poster,
        ))

    if browser_click_through:
        if browser_runner is None:
            if browser_iab_click_through:
                browser_report = _run_browser_iab_smoke_subprocess(
                    base,
                    profile=interaction_profile,
                    case_number=interaction_case_number,
                    service_date=interaction_service_date,
                    upload_photo=browser_upload_photo,
                    upload_pdf=browser_upload_pdf,
                    answer_questions=browser_answer_questions,
                    correction_mode=browser_correction_mode,
                    prepare_replacement=browser_prepare_replacement,
                    prepare_packet=browser_prepare_packet,
                    record_helper=browser_record_helper,
                    apply_history=browser_apply_history,
                )
            else:
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
                        upload_photo=browser_upload_photo,
                        upload_pdf=browser_upload_pdf,
                        answer_questions=browser_answer_questions,
                        correction_mode=browser_correction_mode,
                        prepare_replacement=browser_prepare_replacement,
                        prepare_packet=browser_prepare_packet,
                        record_helper=browser_record_helper,
                    )
        else:
            browser_report = browser_runner(
                base,
                profile=interaction_profile,
                case_number=interaction_case_number,
                service_date=interaction_service_date,
                upload_photo=browser_upload_photo,
                upload_pdf=browser_upload_pdf,
                answer_questions=browser_answer_questions,
                correction_mode=browser_correction_mode,
                prepare_replacement=browser_prepare_replacement,
                prepare_packet=browser_prepare_packet,
                record_helper=browser_record_helper,
                apply_history=browser_apply_history,
                iab_click_through=browser_iab_click_through,
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
    parser.add_argument("--source-upload-checks", action="store_true", help="Upload disposable synthetic photo/PDF sources through the API and verify Source Evidence/Review Attention without preparing PDFs or drafts.")
    parser.add_argument("--supporting-attachment-checks", action="store_true", help="Upload a disposable synthetic declaration/proof PDF through the attachment API and verify it cannot prepare PDFs, record drafts, or call Gmail.")
    parser.add_argument("--source-upload-profile", default="", help="Optional profile key to pass to source upload smoke. Defaults to Auto-detect.")
    parser.add_argument("--interaction-profile", default="example_interpreting")
    parser.add_argument("--interaction-case-number", default="999/26.0SMOKE")
    parser.add_argument("--interaction-service-date", default="2026-05-04")
    parser.add_argument("--browser-click-through", action="store_true", help="Opt-in real browser review-flow click-through. Does not click prepare or record drafts unless the explicit browser prepare flags are used.")
    parser.add_argument("--browser-iab-click-through", action="store_true", help="Use the Codex in-app Browser/IAB runner for browser click-through instead of optional Python Playwright.")
    parser.add_argument("--browser-upload-photo", action="store_true", help="With --browser-click-through, upload a disposable synthetic photo and verify source evidence without preparing artifacts.")
    parser.add_argument("--browser-upload-pdf", action="store_true", help="With --browser-click-through, upload a disposable synthetic notification PDF and verify recovered review fields without preparing artifacts.")
    parser.add_argument("--browser-answer-questions", action="store_true", help="With --browser-click-through, intentionally leave one required field blank, apply compact numbered answers, and rerun review without preparing artifacts.")
    parser.add_argument("--browser-correction-mode", action="store_true", help="With --browser-click-through, check draft lifecycle/correction UI without preparing a replacement draft.")
    parser.add_argument("--browser-apply-history", action="store_true", help="With --browser-iab-click-through, check the LegalPDF Apply History, Detail, and read-only Restore Plan UI without writing artifacts.")
    parser.add_argument("--browser-prepare-replacement", action="store_true", help="With --browser-click-through and --browser-correction-mode, click replacement prepare. This can create local PDF/payload artifacts but still never records drafts or calls Gmail.")
    parser.add_argument("--browser-prepare-packet", action="store_true", help="With --browser-click-through, also click packet prepare. This can create local PDF/payload artifacts.")
    parser.add_argument("--browser-record-helper", action="store_true", help="With --browser-click-through and packet prepare, parse fake Gmail IDs and autofill record fields without recording.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_smoke(
        args.base_url,
        timeout=args.timeout,
        interaction_checks=args.interaction_checks,
        source_upload_checks=args.source_upload_checks,
        supporting_attachment_checks=args.supporting_attachment_checks,
        source_upload_profile=args.source_upload_profile,
        interaction_profile=args.interaction_profile,
        interaction_case_number=args.interaction_case_number,
        interaction_service_date=args.interaction_service_date,
        browser_click_through=args.browser_click_through,
        browser_iab_click_through=args.browser_iab_click_through,
        browser_upload_photo=args.browser_upload_photo,
        browser_upload_pdf=args.browser_upload_pdf,
        browser_answer_questions=args.browser_answer_questions,
        browser_correction_mode=args.browser_correction_mode,
        browser_apply_history=args.browser_apply_history,
        browser_prepare_replacement=args.browser_prepare_replacement,
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
