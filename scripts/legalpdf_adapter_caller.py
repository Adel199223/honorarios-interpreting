from __future__ import annotations

import argparse
from io import BytesIO
import json
import uuid
import urllib.parse
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JsonFetcher = Callable[[str], Any]
PostJsonFetcher = Callable[[str, dict[str, Any]], Any]
PostMultipartFetcher = Callable[[str, dict[str, str], str, bytes, str], Any]

ADAPTER_HEALTH_ENDPOINT = "/api/health"
ADAPTER_CONTRACT_ENDPOINT = "/api/integration/adapter-contract"
REQUIRED_ADAPTER_ENDPOINTS = (
    "/api/sources/upload",
    "/api/review",
    "/api/review/apply-answers",
    "/api/prepare/preflight",
    "/api/prepare",
    "/api/gmail/manual-handoff",
    "/api/drafts/record",
)
STALE_PREPARED_REVIEW_TOKEN = "stale-prepared-token"
EXPECTED_PREPARED_REVIEW_BINDING_FIELDS = {
    "handoff_required_fields": (
        "payload",
        "prepared_manifest",
        "prepared_review_token",
        "review_fingerprint",
    ),
    "record_required_fields": (
        "payload",
        "prepared_manifest",
        "prepared_review_token",
        "review_fingerprint",
        "gmail_handoff_reviewed",
        "draft_id",
        "message_id",
        "thread_id",
    ),
    "gmail_api_create_required_fields": (
        "payload",
        "prepared_manifest",
        "prepared_review_token",
        "review_fingerprint",
        "gmail_handoff_reviewed",
    ),
}
EXPECTED_PREPARED_REVIEW_BINDING_VALUES = {
    "preflight_response_field": "preflight_review",
    "prepare_request_field": "preflight_review",
    "prepare_response_field": "prepared_review",
}
EXPECTED_OPTIONAL_GMAIL_DRAFT_API_BOUNDARY_VALUES = {
    "status": "optional",
    "create_endpoint": "/api/gmail/drafts/create",
    "verify_endpoint": "/api/gmail/drafts/verify",
    "create_action": "users.drafts.create",
    "verify_action": "users.drafts.get",
    "draft_only": True,
    "send_allowed": False,
    "verify_read_only": True,
    "verify_local_records_changed": False,
}
EXPECTED_OPTIONAL_GMAIL_DRAFT_API_FORBIDDEN_ACTIONS = (
    "users.messages.send",
    "users.drafts.send",
    "users.messages.trash",
    "users.messages.delete",
    "users.messages.list",
    "users.drafts.delete",
)


@dataclass(frozen=True)
class AdapterContractValidation:
    ready: bool
    send_allowed: bool
    write_allowed: bool
    legalpdf_write_allowed: bool
    missing_endpoints: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterSequenceResult:
    checks: list[dict[str, Any]]
    prepared_review_bound: bool = False
    draft_payload_present: bool = False
    manual_handoff_ready: bool = False
    stale_manual_handoff_blocked: bool = False
    stale_record_blocked: bool = False
    stale_record_no_local_write: bool = False
    recorded_duplicate_count: int | None = None
    send_allowed: bool = False
    write_allowed: bool = False
    legalpdf_write_allowed: bool = False

    @property
    def failure_count(self) -> int:
        return sum(1 for check in self.checks if check.get("status") != "ready")

    @property
    def status(self) -> str:
        return "ready" if self.failure_count == 0 else "blocked"

    def safe_summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "failure_count": self.failure_count,
            "prepared_review_bound": self.prepared_review_bound,
            "draft_payload_present": self.draft_payload_present,
            "manual_handoff_ready": self.manual_handoff_ready,
            "stale_manual_handoff_blocked": self.stale_manual_handoff_blocked,
            "stale_record_blocked": self.stale_record_blocked,
            "stale_record_no_local_write": self.stale_record_no_local_write,
            "recorded_duplicate_count": self.recorded_duplicate_count,
            "send_allowed": self.send_allowed,
            "write_allowed": self.write_allowed,
            "legalpdf_write_allowed": self.legalpdf_write_allowed,
        }


@dataclass(frozen=True)
class AdapterReadinessResult:
    checks: list[dict[str, Any]]
    health_ready: bool = False
    contract_ready: bool = False
    send_allowed: bool = False
    write_allowed: bool = False
    legalpdf_write_allowed: bool = False
    managed_data_changed: bool = False

    @property
    def failure_count(self) -> int:
        return sum(1 for check in self.checks if check.get("status") != "ready")

    @property
    def status(self) -> str:
        return "ready" if self.failure_count == 0 else "blocked"

    def safe_summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "failure_count": self.failure_count,
            "health_ready": self.health_ready,
            "contract_ready": self.contract_ready,
            "send_allowed": self.send_allowed,
            "write_allowed": self.write_allowed,
            "legalpdf_write_allowed": self.legalpdf_write_allowed,
            "managed_data_changed": self.managed_data_changed,
            "checks": [
                {
                    "name": str(check.get("name") or ""),
                    "status": str(check.get("status") or ""),
                }
                for check in self.checks
            ],
        }


@dataclass(frozen=True)
class AdapterSourceInput:
    profile: str
    source_kind: str
    filename: str
    content: bytes
    expected_case_number: str
    expected_service_date: str
    content_type: str = "application/pdf"
    visible_metadata_text: str = ""
    ai_recovery: str = "off"
    extra_fields: dict[str, str] = field(default_factory=dict)

    def upload_fields(self) -> dict[str, str]:
        fields = {
            "source_kind": str(self.source_kind),
            "profile": str(self.profile),
            "visible_metadata_text": str(self.visible_metadata_text),
            "ai_recovery": str(self.ai_recovery),
        }
        fields.update({str(key): str(value) for key, value in self.extra_fields.items()})
        return fields

    def safe_filename(self) -> str:
        return _safe_multipart_filename(self.filename)


def normalize_base_url(base_url: str) -> str:
    value = str(base_url or "").strip()
    if not value:
        raise ValueError("base_url is required")
    if not urllib.parse.urlparse(value).scheme:
        value = f"http://{value}"
    return value.rstrip("/")


def adapter_url(base_url: str, path: str) -> str:
    return f"{normalize_base_url(base_url)}{path}"


def _read_json_response(response: Any) -> Any:
    return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_json_http(url: str, *, timeout: float = 5.0) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return _read_json_response(response)


def post_json_http(url: str, payload: dict[str, Any], *, timeout: float = 5.0) -> Any:
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
        return _read_json_response(response)


def _safe_multipart_filename(filename: str) -> str:
    return str(filename or "upload.bin").replace("\\", "/").rsplit("/", 1)[-1].replace('"', "")


def post_multipart_http(
    url: str,
    fields: dict[str, str],
    filename: str,
    content: bytes,
    content_type: str,
    *,
    timeout: float = 5.0,
) -> Any:
    boundary = f"----honorarios-adapter-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
            str(value).encode("utf-8"),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode("ascii"),
        f'Content-Disposition: form-data; name="file"; filename="{_safe_multipart_filename(filename)}"\r\n'.encode("ascii"),
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
        return _read_json_response(response)


def build_http_adapter_caller(base_url: str, *, timeout: float = 5.0) -> "LegalPdfAdapterCaller":
    return LegalPdfAdapterCaller(
        base_url,
        fetch_json=lambda url: fetch_json_http(url, timeout=timeout),
        post_json=lambda url, payload: post_json_http(url, payload, timeout=timeout),
        post_multipart=lambda url, fields, filename, content, content_type: post_multipart_http(
            url,
            fields,
            filename,
            content,
            content_type,
            timeout=timeout,
        ),
    )


def prepared_review_request_fields(prepared_review: dict[str, Any]) -> dict[str, str]:
    return {
        "prepared_manifest": str(prepared_review.get("manifest") or "").strip(),
        "prepared_review_token": str(prepared_review.get("prepared_review_token") or "").strip(),
        "review_fingerprint": str(prepared_review.get("review_fingerprint") or "").strip(),
    }


def stale_prepared_review_fields(
    prepared_fields: dict[str, str],
    *,
    stale_token: str = STALE_PREPARED_REVIEW_TOKEN,
) -> dict[str, str]:
    return {**prepared_fields, "prepared_review_token": stale_token}


def adapter_answer_for_field(field: str, *, case_number: str, service_date: str) -> str:
    answers = {
        "case_number": case_number,
        "service_date": service_date,
        "service_date_source": service_date,
        "payment_entity": "Example Court",
        "service_place": "Example Police Station",
        "service_entity": "Example Police / Example Police Station",
        "claim_transport": "yes",
        "transport.destination": "Example City",
        "transport.km_one_way": "12",
        "closing_city": "Example City",
        "closing_date": service_date,
    }
    return answers.get(field, "Example City")


def adapter_numbered_answers(questions: list[Any], *, case_number: str, service_date: str) -> str:
    lines: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        number = question.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            continue
        field = str(question.get("field") or "")
        lines.append(f"{number}. {adapter_answer_for_field(field, case_number=case_number, service_date=service_date)}")
    return "\n".join(lines)


def adapter_questions_are_numbered(questions: list[Any], question_text: str) -> bool:
    if not questions or not question_text.strip():
        return False
    for question in questions:
        if not isinstance(question, dict):
            return False
        number = question.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            return False
        if f"{number}." not in question_text:
            return False
    return True


class LegalPdfAdapterCaller:
    """Small HTTP caller shim for the read-only LegalPDF adapter boundary."""

    def __init__(
        self,
        base_url: str,
        *,
        fetch_json: JsonFetcher,
        post_json: PostJsonFetcher,
        post_multipart: PostMultipartFetcher,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.fetch_json = fetch_json
        self.post_json = post_json
        self.post_multipart = post_multipart

    def url(self, path: str) -> str:
        return adapter_url(self.base_url, path)

    def fetch_health(self) -> Any:
        return self.fetch_json(self.url(ADAPTER_HEALTH_ENDPOINT))

    def fetch_contract(self) -> Any:
        return self.fetch_json(self.url(ADAPTER_CONTRACT_ENDPOINT))

    def validate_contract(self, contract: Any) -> AdapterContractValidation:
        sequence = contract.get("sequence") if isinstance(contract, dict) and isinstance(contract.get("sequence"), list) else []
        endpoints = {
            str(step.get("endpoint") or "")
            for step in sequence
            if isinstance(step, dict)
        }
        missing = sorted(set(REQUIRED_ADAPTER_ENDPOINTS).difference(endpoints))
        gmail_boundary = contract.get("gmail_boundary") if isinstance(contract, dict) and isinstance(contract.get("gmail_boundary"), dict) else {}
        prepared_binding = contract.get("prepared_review_binding") if isinstance(contract, dict) and isinstance(contract.get("prepared_review_binding"), dict) else {}
        optional_gmail_boundary = contract.get("optional_gmail_draft_api_boundary") if isinstance(contract, dict) and isinstance(contract.get("optional_gmail_draft_api_boundary"), dict) else {}
        optional_gmail_boundary_present = bool(optional_gmail_boundary)
        missing_prepared_fields: dict[str, list[str]] = {}
        for key, expected_fields in EXPECTED_PREPARED_REVIEW_BINDING_FIELDS.items():
            actual = prepared_binding.get(key) if isinstance(prepared_binding.get(key), list) else []
            actual_values = {str(item) for item in actual}
            missing_values = [field for field in expected_fields if field not in actual_values]
            if missing_values:
                missing_prepared_fields[key] = missing_values
        mismatched_prepared_values = {
            key: {
                "expected": expected,
                "actual": prepared_binding.get(key),
            }
            for key, expected in EXPECTED_PREPARED_REVIEW_BINDING_VALUES.items()
            if prepared_binding.get(key) != expected
        }
        prepared_binding_ready = (
            isinstance(prepared_binding, dict)
            and prepared_binding.get("send_allowed") is False
            and prepared_binding.get("stale_after_payload_or_manifest_change") is True
            and prepared_binding.get("local_workflow_guard_only") is True
            and not missing_prepared_fields
            and not mismatched_prepared_values
        )
        gmail_boundary_ready = (
            isinstance(gmail_boundary, dict)
            and gmail_boundary.get("required_tool") == "_create_draft"
            and gmail_boundary.get("send_allowed") is False
            and gmail_boundary.get("draft_only") is True
        )
        mismatched_optional_gmail_boundary_values = {
            key: {
                "expected": expected,
                "actual": optional_gmail_boundary.get(key),
            }
            for key, expected in EXPECTED_OPTIONAL_GMAIL_DRAFT_API_BOUNDARY_VALUES.items()
            if optional_gmail_boundary_present and optional_gmail_boundary.get(key) != expected
        }
        optional_forbidden_actions = (
            {str(item) for item in optional_gmail_boundary.get("forbidden_actions", [])}
            if isinstance(optional_gmail_boundary.get("forbidden_actions"), list)
            else set()
        )
        missing_optional_forbidden_actions = [
            action
            for action in EXPECTED_OPTIONAL_GMAIL_DRAFT_API_FORBIDDEN_ACTIONS
            if action not in optional_forbidden_actions
        ] if optional_gmail_boundary_present else []
        optional_gmail_boundary_ready = (
            not optional_gmail_boundary_present
            or (
                not mismatched_optional_gmail_boundary_values
                and not missing_optional_forbidden_actions
            )
        )
        send_allowed = bool(contract.get("send_allowed")) if isinstance(contract, dict) else False
        write_allowed = bool(contract.get("write_allowed")) if isinstance(contract, dict) else False
        legalpdf_write_allowed = bool(contract.get("legalpdf_write_allowed")) if isinstance(contract, dict) else False
        ready = (
            isinstance(contract, dict)
            and contract.get("status") == "ready"
            and contract.get("recommended_gmail_mode") == "manual_handoff"
            and contract.get("draft_only") is True
            and contract.get("send_allowed") is False
            and contract.get("write_allowed") is False
            and contract.get("legalpdf_write_allowed") is False
            and contract.get("managed_data_changed") is False
            and gmail_boundary_ready
            and prepared_binding_ready
            and optional_gmail_boundary_ready
        )
        return AdapterContractValidation(
            ready=ready,
            send_allowed=send_allowed,
            write_allowed=write_allowed,
            legalpdf_write_allowed=legalpdf_write_allowed,
            missing_endpoints=missing,
            details={
                "status": contract.get("status") if isinstance(contract, dict) else None,
                "recommended_gmail_mode": contract.get("recommended_gmail_mode") if isinstance(contract, dict) else None,
                "draft_only": contract.get("draft_only") if isinstance(contract, dict) else None,
                "managed_data_changed": contract.get("managed_data_changed") if isinstance(contract, dict) else None,
                "required_tool": gmail_boundary.get("required_tool"),
                "gmail_boundary_ready": gmail_boundary_ready,
                "gmail_boundary_send_allowed": gmail_boundary.get("send_allowed"),
                "gmail_boundary_draft_only": gmail_boundary.get("draft_only"),
                "optional_gmail_draft_api_boundary_ready": optional_gmail_boundary_ready,
                "optional_gmail_draft_api_boundary_present": optional_gmail_boundary_present,
                "optional_gmail_create_endpoint": optional_gmail_boundary.get("create_endpoint"),
                "optional_gmail_verify_endpoint": optional_gmail_boundary.get("verify_endpoint"),
                "optional_gmail_create_action": optional_gmail_boundary.get("create_action"),
                "optional_gmail_verify_action": optional_gmail_boundary.get("verify_action"),
                "optional_gmail_send_allowed": optional_gmail_boundary.get("send_allowed"),
                "optional_gmail_draft_only": optional_gmail_boundary.get("draft_only"),
                "optional_gmail_verify_read_only": optional_gmail_boundary.get("verify_read_only"),
                "optional_gmail_verify_local_records_changed": optional_gmail_boundary.get("verify_local_records_changed"),
                "missing_optional_gmail_forbidden_actions": missing_optional_forbidden_actions,
                "mismatched_optional_gmail_boundary_values": mismatched_optional_gmail_boundary_values,
                "prepared_review_binding_ready": prepared_binding_ready,
                "missing_prepared_review_fields": missing_prepared_fields,
                "mismatched_prepared_review_values": mismatched_prepared_values,
                "endpoints": sorted(endpoints),
            },
        )

    def upload_source(
        self,
        fields: dict[str, str],
        filename: str,
        content: bytes,
        content_type: str,
    ) -> Any:
        return self.post_multipart(self.url("/api/sources/upload"), fields, filename, content, content_type)

    def review_intake(self, intake: dict[str, Any]) -> Any:
        return self.post_json(self.url("/api/review"), {"intake": intake})

    def apply_numbered_answers(self, intake: dict[str, Any], answers: str) -> Any:
        return self.post_json(self.url("/api/review/apply-answers"), {"intake": intake, "answers": answers})

    def prepare_preflight(self, intakes: list[dict[str, Any]], *, packet_mode: bool = True) -> Any:
        return self.post_json(self.url("/api/prepare/preflight"), {"intakes": intakes, "packet_mode": packet_mode})

    def prepare_artifacts(
        self,
        intakes: list[dict[str, Any]],
        *,
        preflight_review: dict[str, Any],
        packet_mode: bool = True,
    ) -> Any:
        return self.post_json(
            self.url("/api/prepare"),
            {
                "intakes": intakes,
                "render_previews": False,
                "packet_mode": packet_mode,
                "preflight_review": preflight_review,
            },
        )

    def manual_handoff(self, payload: str, prepared_fields: dict[str, str]) -> Any:
        return self.post_json(self.url("/api/gmail/manual-handoff"), {"payload": payload, **prepared_fields})

    def record_draft(
        self,
        payload: str,
        *,
        draft_id: str,
        message_id: str,
        thread_id: str,
        notes: str,
        prepared_fields: dict[str, str],
    ) -> Any:
        return self.post_json(
            self.url("/api/drafts/record"),
            {
                "payload": payload,
                "draft_id": draft_id,
                "message_id": message_id,
                "thread_id": thread_id,
                "status": "active",
                "notes": notes,
                "gmail_handoff_reviewed": True,
                **prepared_fields,
            },
        )


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


def _payload_flag_true(payload: Any, key: str) -> bool:
    if isinstance(payload, dict):
        for item_key, item_value in payload.items():
            if item_key == key and item_value is True:
                return True
            if _payload_flag_true(item_value, key):
                return True
    elif isinstance(payload, list):
        return any(_payload_flag_true(item, key) for item in payload)
    return False


def _adapter_contract_checks(validation: AdapterContractValidation) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.append(_check(
        "adapter_contract_read_only",
        validation.ready,
        "Adapter contract is read-only, draft-only, and Manual Draft Handoff first." if validation.ready else "Adapter contract does not expose the expected read-only manual-handoff boundary.",
        {
            "status": validation.details.get("status"),
            "recommended_gmail_mode": validation.details.get("recommended_gmail_mode"),
            "write_allowed": validation.write_allowed,
            "legalpdf_write_allowed": validation.legalpdf_write_allowed,
            "managed_data_changed": validation.details.get("managed_data_changed"),
            "required_tool": validation.details.get("required_tool"),
            "gmail_boundary_ready": validation.details.get("gmail_boundary_ready"),
            "gmail_boundary_send_allowed": validation.details.get("gmail_boundary_send_allowed"),
            "gmail_boundary_draft_only": validation.details.get("gmail_boundary_draft_only"),
        },
    ))
    checks.append(_check(
        "adapter_contract_gmail_boundary",
        validation.details.get("gmail_boundary_ready") is True,
        "Adapter contract keeps the nested Gmail boundary draft-only and send-disabled."
        if validation.details.get("gmail_boundary_ready") is True
        else "Adapter contract Gmail boundary is missing draft-only or send-disabled fields.",
        {
            "required_tool": validation.details.get("required_tool"),
            "gmail_boundary_send_allowed": validation.details.get("gmail_boundary_send_allowed"),
            "gmail_boundary_draft_only": validation.details.get("gmail_boundary_draft_only"),
        },
    ))
    optional_gmail_boundary_present = validation.details.get("optional_gmail_draft_api_boundary_present") is True
    checks.append(_check(
        "adapter_contract_optional_gmail_draft_api_boundary",
        validation.details.get("optional_gmail_draft_api_boundary_ready") is True,
        "Adapter contract keeps optional Gmail Draft API create/verify draft-only and verify read-only."
        if optional_gmail_boundary_present and validation.details.get("optional_gmail_draft_api_boundary_ready") is True
        else (
            "Adapter contract omits optional Gmail Draft API metadata; Manual Draft Handoff remains the required path."
            if validation.details.get("optional_gmail_draft_api_boundary_ready") is True
            else "Adapter contract optional Gmail Draft API boundary is send-capable or verify is not read-only."
        ),
        {
            "present": optional_gmail_boundary_present,
            "create_endpoint": validation.details.get("optional_gmail_create_endpoint"),
            "verify_endpoint": validation.details.get("optional_gmail_verify_endpoint"),
            "create_action": validation.details.get("optional_gmail_create_action"),
            "verify_action": validation.details.get("optional_gmail_verify_action"),
            "send_allowed": validation.details.get("optional_gmail_send_allowed"),
            "draft_only": validation.details.get("optional_gmail_draft_only"),
            "verify_read_only": validation.details.get("optional_gmail_verify_read_only"),
            "verify_local_records_changed": validation.details.get("optional_gmail_verify_local_records_changed"),
            "missing_forbidden_actions": validation.details.get("missing_optional_gmail_forbidden_actions"),
            "mismatched_values": validation.details.get("mismatched_optional_gmail_boundary_values"),
        },
    ))
    checks.append(_check(
        "adapter_contract_prepared_review_binding",
        validation.details.get("prepared_review_binding_ready") is True,
        "Adapter contract advertises the prepared-review fields required for handoff, Gmail API create, and local recording."
        if validation.details.get("prepared_review_binding_ready") is True
        else "Adapter contract is missing prepared-review binding fields required by the caller.",
        {
            "missing_prepared_review_fields": validation.details.get("missing_prepared_review_fields"),
            "mismatched_prepared_review_values": validation.details.get("mismatched_prepared_review_values"),
        },
    ))
    endpoints = validation.details.get("endpoints")
    checks.append(_check(
        "adapter_contract_sequence",
        not validation.missing_endpoints,
        "Adapter contract advertises the safe review, preflight, prepare, handoff, and record sequence." if not validation.missing_endpoints else "Adapter contract is missing expected workflow endpoints.",
        {"missing": validation.missing_endpoints, "endpoints": endpoints if isinstance(endpoints, list) else []},
    ))
    return checks


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


def _post_expected_blocked_json(
    post_json: PostJsonFetcher,
    url: str,
    payload: dict[str, Any],
    check_name: str,
) -> tuple[Any | None, dict[str, Any] | None]:
    try:
        return post_json(url, payload), None
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            return None, _check(check_name, False, f"Expected HTTP 400 from {url}, got HTTP {exc.code}.")
        try:
            body = exc.read().decode("utf-8", errors="replace")
            close = getattr(exc, "close", None)
            if callable(close):
                close()
            return json.loads(body), None
        except (ValueError, json.JSONDecodeError) as parse_exc:
            return None, _check(check_name, False, f"Could not parse blocked JSON response from {url}: {parse_exc}")
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return None, _check(check_name, False, f"Could not call {url}: {exc}")


def _prepared_review_blocked(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    message = str(payload.get("message") or payload.get("detail") or "").lower()
    return (
        payload.get("status") == "blocked"
        and payload.get("send_allowed") is False
        and "prepared review" in message
        and ("stale" in message or "current" in message or "again" in message)
    )


def _history_record_snapshot(history: Any) -> dict[str, str]:
    if not isinstance(history, dict):
        return {"draft_log": "", "duplicates": ""}
    return {
        "draft_log": json.dumps(history.get("draft_log") or [], ensure_ascii=True, sort_keys=True),
        "duplicates": json.dumps(history.get("duplicates") or [], ensure_ascii=True, sort_keys=True),
    }


def _fetch_history_record_snapshot(
    fetch_json: JsonFetcher,
    base_url: str,
    check_name: str,
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    try:
        return _history_record_snapshot(fetch_json(adapter_url(base_url, "/api/history"))), None
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return None, _check(check_name, False, f"Could not load local draft history from /api/history: {exc}")


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


def synthetic_notification_pdf(case_number: str, service_date: str, *, recipient_email: str = "court@example.test") -> bytes:
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
    document.drawString(72, 660, f"Email: {recipient_email}")
    document.save()
    return output.getvalue()


def _check_by_name(checks: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for check in checks:
        if check.get("name") == name:
            return check
    return {}


def _check_is_ready(checks: list[dict[str, Any]], name: str) -> bool:
    return _check_by_name(checks, name).get("status") == "ready"


def _adapter_sequence_result_from_checks(checks: list[dict[str, Any]]) -> AdapterSequenceResult:
    prepare_details = _check_by_name(checks, "adapter_prepare_ready").get("details")
    if not isinstance(prepare_details, dict):
        prepare_details = {}
    record_details = _check_by_name(checks, "adapter_record_draft").get("details")
    if not isinstance(record_details, dict):
        record_details = {}
    duplicate_count = record_details.get("recorded_duplicate_count")
    return AdapterSequenceResult(
        checks=checks,
        prepared_review_bound=(
            prepare_details.get("prepared_manifest_present") is True
            and prepare_details.get("prepared_token_present") is True
            and prepare_details.get("review_fingerprint_present") is True
        ),
        draft_payload_present=prepare_details.get("draft_payload_present") is True,
        manual_handoff_ready=_check_is_ready(checks, "adapter_manual_handoff_packet"),
        stale_manual_handoff_blocked=_check_is_ready(checks, "adapter_manual_handoff_rejects_stale_review"),
        stale_record_blocked=_check_is_ready(checks, "adapter_record_rejects_stale_review"),
        stale_record_no_local_write=_check_is_ready(checks, "adapter_record_stale_no_local_write"),
        recorded_duplicate_count=duplicate_count if isinstance(duplicate_count, int) else None,
    )


def run_adapter_readiness_result(
    base_url: str,
    *,
    fetch_json: JsonFetcher,
) -> AdapterReadinessResult:
    checks: list[dict[str, Any]] = []
    caller = LegalPdfAdapterCaller(
        base_url,
        fetch_json=fetch_json,
        post_json=lambda _url, _payload: {},
        post_multipart=lambda _url, _fields, _filename, _content, _content_type: {},
    )
    try:
        health = caller.fetch_health()
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        checks.append(_check("adapter_health_fetch", False, f"Could not load adapter health endpoint: {exc}"))
        return AdapterReadinessResult(checks=checks)

    checks.append(_send_allowed_check(
        "adapter_health_send_allowed",
        health,
        "Adapter health keeps send_allowed false.",
    ))
    health_ready = (
        isinstance(health, dict)
        and health.get("status") == "ready"
        and health.get("app") == "LegalPDF Honorários"
        and health.get("send_allowed") is False
        and health.get("write_allowed") is False
        and health.get("managed_data_changed") is False
    )
    checks.append(_check(
        "adapter_health_read_only",
        health_ready,
        "Adapter health is ready, read-only, and secret-free." if health_ready else "Adapter health is missing ready/read-only safety fields.",
        {
            "status": health.get("status") if isinstance(health, dict) else None,
            "app": health.get("app") if isinstance(health, dict) else None,
            "send_allowed": health.get("send_allowed") if isinstance(health, dict) else None,
            "write_allowed": health.get("write_allowed") if isinstance(health, dict) else None,
            "managed_data_changed": health.get("managed_data_changed") if isinstance(health, dict) else None,
        },
    ))
    health_send_allowed = _payload_flag_true(health, "send_allowed")
    health_write_allowed = _payload_flag_true(health, "write_allowed")
    health_managed_changed = _payload_flag_true(health, "managed_data_changed")
    health_legalpdf_write_allowed = _payload_flag_true(health, "legalpdf_write_allowed")
    if not health_ready:
        return AdapterReadinessResult(
            checks=checks,
            health_ready=False,
            contract_ready=False,
            send_allowed=health_send_allowed,
            write_allowed=health_write_allowed,
            legalpdf_write_allowed=health_legalpdf_write_allowed,
            managed_data_changed=health_managed_changed,
        )

    try:
        contract = caller.fetch_contract()
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        checks.append(_check("adapter_contract_fetch", False, f"Could not load LegalPDF adapter contract: {exc}"))
        return AdapterReadinessResult(
            checks=checks,
            health_ready=True,
            contract_ready=False,
            send_allowed=health_send_allowed,
            write_allowed=health_write_allowed,
            legalpdf_write_allowed=health_legalpdf_write_allowed,
            managed_data_changed=health_managed_changed,
        )

    checks.append(_send_allowed_check(
        "adapter_contract_send_allowed",
        contract,
        "LegalPDF adapter contract keeps send_allowed false.",
    ))
    validation = caller.validate_contract(contract)
    checks.extend(_adapter_contract_checks(validation))
    contract_ready = validation.ready and not validation.missing_endpoints
    return AdapterReadinessResult(
        checks=checks,
        health_ready=True,
        contract_ready=contract_ready,
        send_allowed=health_send_allowed or validation.send_allowed,
        write_allowed=health_write_allowed or validation.write_allowed,
        legalpdf_write_allowed=health_legalpdf_write_allowed or validation.legalpdf_write_allowed,
        managed_data_changed=health_managed_changed or bool(validation.details.get("managed_data_changed") is True),
    )


def run_adapter_sequence(
    base_url: str,
    *,
    fetch_json: JsonFetcher,
    post_json: PostJsonFetcher,
    post_multipart: PostMultipartFetcher,
    source: AdapterSourceInput,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    caller = LegalPdfAdapterCaller(
        base_url,
        fetch_json=fetch_json,
        post_json=post_json,
        post_multipart=post_multipart,
    )
    readiness = run_adapter_readiness_result(base_url, fetch_json=fetch_json)
    checks.extend(readiness.checks)
    if readiness.status != "ready":
        return checks

    try:
        upload_response = caller.upload_source(
            source.upload_fields(),
            source.safe_filename(),
            source.content,
            source.content_type,
        )
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        checks.append(_check("adapter_source_upload_evidence", False, f"Could not upload adapter source: {exc}"))
        return checks
    checks.append(_send_allowed_check(
        "adapter_source_upload_send_allowed",
        upload_response,
        "Adapter source upload keeps send_allowed false.",
    ))
    candidate_intake = upload_response.get("candidate_intake") if isinstance(upload_response, dict) else {}
    source_ready = (
        isinstance(upload_response, dict)
        and upload_response.get("status") == "uploaded"
        and isinstance(candidate_intake, dict)
        and candidate_intake.get("case_number") == source.expected_case_number
        and candidate_intake.get("service_date") == source.expected_service_date
        and _upload_response_has_attention(upload_response)
    )
    checks.append(_check(
        "adapter_source_upload_evidence",
        source_ready,
        "Adapter source upload recovers candidate intake and Review Attention before review." if source_ready else "Adapter source upload did not return usable candidate evidence.",
        {
            "status": upload_response.get("status") if isinstance(upload_response, dict) else None,
            "case_number": candidate_intake.get("case_number") if isinstance(candidate_intake, dict) else None,
            "service_date": candidate_intake.get("service_date") if isinstance(candidate_intake, dict) else None,
            "attention": _attention_summary(upload_response),
        },
    ))
    if not source_ready:
        return checks

    review_seed_intake = json.loads(json.dumps(candidate_intake))
    if isinstance(review_seed_intake, dict):
        review_seed_intake.pop("closing_date", None)

    review_response, error_check = _post_workflow_json(
        caller.post_json,
        caller.url("/api/review"),
        {"intake": review_seed_intake},
        "adapter_review_missing_questions",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "adapter_review_send_allowed",
        review_response,
        "Adapter review keeps send_allowed false.",
    ))
    questions = review_response.get("questions") if isinstance(review_response, dict) and isinstance(review_response.get("questions"), list) else []
    question_text = str(review_response.get("question_text") or "") if isinstance(review_response, dict) else ""
    review_intake = {}
    if isinstance(review_response, dict):
        candidate = review_response.get("intake") or review_response.get("effective_intake") or candidate_intake
        review_intake = candidate if isinstance(candidate, dict) else {}
    numbered_questions = adapter_questions_are_numbered(questions, question_text)
    review_needs_answers = (
        isinstance(review_response, dict)
        and review_response.get("status") in {"needs_info", "blocked"}
        and isinstance(review_intake, dict)
        and bool(review_intake)
        and numbered_questions
    )
    checks.append(_check(
        "adapter_review_missing_questions",
        review_needs_answers,
        "Adapter caller review surfaces numbered missing questions before preparation." if review_needs_answers else "Adapter caller review did not surface numbered missing questions.",
        {
            "status": review_response.get("status") if isinstance(review_response, dict) else None,
            "question_count": len(questions),
            "fields": [question.get("field") for question in questions if isinstance(question, dict)],
            "numbered_questions": numbered_questions,
        },
    ))
    if not review_needs_answers:
        return checks

    answer_text = adapter_numbered_answers(
        questions,
        case_number=source.expected_case_number,
        service_date=source.expected_service_date,
    )
    apply_response, error_check = _post_workflow_json(
        caller.post_json,
        caller.url("/api/review/apply-answers"),
        {"intake": review_intake, "answers": answer_text},
        "adapter_apply_answers_ready",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "adapter_apply_answers_send_allowed",
        apply_response,
        "Adapter numbered-answer review keeps send_allowed false.",
    ))
    reviewed_intake = {}
    if isinstance(apply_response, dict):
        candidate = apply_response.get("intake") or apply_response.get("effective_intake") or review_intake
        reviewed_intake = candidate if isinstance(candidate, dict) else {}
    draft_text = str(apply_response.get("draft_text") or "") if isinstance(apply_response, dict) else ""
    apply_ready = (
        isinstance(apply_response, dict)
        and apply_response.get("status") == "ready"
        and isinstance(reviewed_intake, dict)
        and bool(reviewed_intake)
        and bool(draft_text.strip())
    )
    checks.append(_check(
        "adapter_apply_answers_ready",
        apply_ready,
        "Adapter numbered answers rerun review into a ready intake and Portuguese draft text." if apply_ready else "Adapter numbered answers did not produce a ready review.",
        {
            "status": apply_response.get("status") if isinstance(apply_response, dict) else None,
            "applied_fields": apply_response.get("applied_fields") if isinstance(apply_response, dict) else None,
            "draft_text_present": bool(draft_text.strip()),
        },
    ))
    if not apply_ready:
        return checks

    preflight_response, error_check = _post_workflow_json(
        caller.post_json,
        caller.url("/api/prepare/preflight"),
        {"intakes": [reviewed_intake], "packet_mode": True},
        "adapter_preflight_ready",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "adapter_preflight_send_allowed",
        preflight_response,
        "Adapter preflight keeps send_allowed false.",
    ))
    preflight_review = preflight_response.get("preflight_review") if isinstance(preflight_response, dict) else {}
    preflight_ready = (
        isinstance(preflight_response, dict)
        and preflight_response.get("status") == "ready"
        and preflight_response.get("artifact_effect") == "none"
        and preflight_response.get("write_allowed") is False
        and isinstance(preflight_review, dict)
        and bool(preflight_review.get("review_fingerprint"))
        and bool(preflight_review.get("preflight_review_token"))
    )
    checks.append(_check(
        "adapter_preflight_ready",
        preflight_ready,
        "Adapter preflight validates the current request without writing artifacts." if preflight_ready else "Adapter preflight did not return a ready signed review.",
        {
            "status": preflight_response.get("status") if isinstance(preflight_response, dict) else None,
            "artifact_effect": preflight_response.get("artifact_effect") if isinstance(preflight_response, dict) else None,
            "write_allowed": preflight_response.get("write_allowed") if isinstance(preflight_response, dict) else None,
            "preflight_token_present": bool(preflight_review.get("preflight_review_token")) if isinstance(preflight_review, dict) else False,
        },
    ))
    if not preflight_ready:
        return checks

    prepare_response, error_check = _post_workflow_json(
        caller.post_json,
        caller.url("/api/prepare"),
        {
            "intakes": [reviewed_intake],
            "render_previews": False,
            "packet_mode": True,
            "preflight_review": preflight_review,
        },
        "adapter_prepare_ready",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "adapter_prepare_send_allowed",
        prepare_response,
        "Adapter prepare keeps send_allowed false.",
    ))
    prepared_review = prepare_response.get("prepared_review") if isinstance(prepare_response, dict) else {}
    items = prepare_response.get("items") if isinstance(prepare_response, dict) else []
    first_item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
    packet = prepare_response.get("packet") if isinstance(prepare_response, dict) and isinstance(prepare_response.get("packet"), dict) else {}
    target = packet or first_item
    draft_payload = str(target.get("draft_payload") or "")
    gmail_args = target.get("gmail_create_draft_args") if isinstance(target.get("gmail_create_draft_args"), dict) else {}
    attachment_files = gmail_args.get("attachment_files") if isinstance(gmail_args, dict) else None
    underlying = target.get("underlying_requests") if isinstance(target.get("underlying_requests"), list) else []
    prepared_fields = prepared_review_request_fields(prepared_review if isinstance(prepared_review, dict) else {})
    prepare_ready = (
        isinstance(prepare_response, dict)
        and prepare_response.get("status") == "prepared"
        and bool(packet)
        and bool(draft_payload)
        and isinstance(attachment_files, list)
        and bool(attachment_files)
        and isinstance(underlying, list)
        and bool(underlying)
        and all(prepared_fields.values())
    )
    checks.append(_check(
        "adapter_prepare_ready",
        prepare_ready,
        "Adapter prepare produced a draft payload bound to a prepared-review token." if prepare_ready else "Adapter prepare did not produce a token-bound draft payload.",
        {
            "status": prepare_response.get("status") if isinstance(prepare_response, dict) else None,
            "packet_present": bool(packet),
            "draft_payload_present": bool(draft_payload),
            "attachment_count": len(attachment_files) if isinstance(attachment_files, list) else None,
            "underlying_request_count": len(underlying) if isinstance(underlying, list) else None,
            "prepared_manifest_present": bool(prepared_fields["prepared_manifest"]),
            "prepared_token_present": bool(prepared_fields["prepared_review_token"]),
            "review_fingerprint_present": bool(prepared_fields["review_fingerprint"]),
        },
    ))
    if not prepare_ready:
        return checks

    stale_prepared_fields = stale_prepared_review_fields(prepared_fields)
    stale_handoff_response, error_check = _post_expected_blocked_json(
        caller.post_json,
        caller.url("/api/gmail/manual-handoff"),
        {"payload": draft_payload, **stale_prepared_fields},
        "adapter_manual_handoff_rejects_stale_review",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "adapter_manual_handoff_stale_send_allowed",
        stale_handoff_response,
        "Adapter stale Manual Draft Handoff rejection keeps send_allowed false.",
    ))
    stale_handoff_blocked = (
        isinstance(stale_handoff_response, dict)
        and _prepared_review_blocked(stale_handoff_response)
        and not bool(stale_handoff_response.get("copyable_prompt"))
    )
    checks.append(_check(
        "adapter_manual_handoff_rejects_stale_review",
        stale_handoff_blocked,
        "Adapter Manual Draft Handoff rejects stale prepared-review credentials before returning a handoff packet." if stale_handoff_blocked else "Adapter Manual Draft Handoff did not reject stale prepared-review credentials.",
        {
            "status": stale_handoff_response.get("status") if isinstance(stale_handoff_response, dict) else None,
            "message": stale_handoff_response.get("message") if isinstance(stale_handoff_response, dict) else None,
            "copyable_prompt_present": bool(stale_handoff_response.get("copyable_prompt")) if isinstance(stale_handoff_response, dict) else None,
        },
    ))
    if not stale_handoff_blocked:
        return checks

    handoff_response, error_check = _post_workflow_json(
        caller.post_json,
        caller.url("/api/gmail/manual-handoff"),
        {"payload": draft_payload, **prepared_fields},
        "adapter_manual_handoff_packet",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "adapter_manual_handoff_send_allowed",
        handoff_response,
        "Adapter Manual Draft Handoff keeps send_allowed false.",
    ))
    handoff_ready = (
        isinstance(handoff_response, dict)
        and handoff_response.get("status") == "ready"
        and handoff_response.get("mode") == "manual_handoff"
        and handoff_response.get("gmail_tool") == "_create_draft"
        and bool(handoff_response.get("copyable_prompt"))
        and isinstance(handoff_response.get("attachment_files"), list)
    )
    checks.append(_check(
        "adapter_manual_handoff_packet",
        handoff_ready,
        "Adapter Manual Draft Handoff returns copy-ready draft-only args." if handoff_ready else "Adapter Manual Draft Handoff did not return the expected draft-only packet.",
        {
            "status": handoff_response.get("status") if isinstance(handoff_response, dict) else None,
            "mode": handoff_response.get("mode") if isinstance(handoff_response, dict) else None,
            "gmail_tool": handoff_response.get("gmail_tool") if isinstance(handoff_response, dict) else None,
            "attachment_count": len(handoff_response.get("attachment_files") or []) if isinstance(handoff_response, dict) and isinstance(handoff_response.get("attachment_files"), list) else None,
        },
    ))
    if not handoff_ready:
        return checks

    before_stale_record_snapshot, error_check = _fetch_history_record_snapshot(
        caller.fetch_json,
        caller.base_url,
        "adapter_record_stale_no_local_write",
    )
    if error_check:
        checks.append(error_check)
        return checks

    stale_record_response, error_check = _post_expected_blocked_json(
        caller.post_json,
        caller.url("/api/drafts/record"),
        {
            "payload": draft_payload,
            "draft_id": "draft-stale-adapter-smoke",
            "message_id": "message-stale-adapter-smoke",
            "thread_id": "thread-stale-adapter-smoke",
            "status": "active",
            "notes": "Stale LegalPDF adapter contract smoke record.",
            "gmail_handoff_reviewed": True,
            **stale_prepared_fields,
        },
        "adapter_record_rejects_stale_review",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "adapter_record_stale_send_allowed",
        stale_record_response,
        "Adapter stale draft-record rejection keeps send_allowed false.",
    ))
    stale_record_blocked = (
        isinstance(stale_record_response, dict)
        and _prepared_review_blocked(stale_record_response)
        and stale_record_response.get("status") != "recorded"
    )
    checks.append(_check(
        "adapter_record_rejects_stale_review",
        stale_record_blocked,
        "Adapter draft recording rejects stale prepared-review credentials before writing local records." if stale_record_blocked else "Adapter draft recording did not reject stale prepared-review credentials.",
        {
            "status": stale_record_response.get("status") if isinstance(stale_record_response, dict) else None,
            "message": stale_record_response.get("message") if isinstance(stale_record_response, dict) else None,
            "recorded_duplicate_count": stale_record_response.get("recorded_duplicate_count") if isinstance(stale_record_response, dict) else None,
        },
    ))
    if not stale_record_blocked:
        return checks

    after_stale_record_snapshot, error_check = _fetch_history_record_snapshot(
        caller.fetch_json,
        caller.base_url,
        "adapter_record_stale_no_local_write",
    )
    if error_check:
        checks.append(error_check)
        return checks
    stale_record_no_write = before_stale_record_snapshot == after_stale_record_snapshot
    checks.append(_check(
        "adapter_record_stale_no_local_write",
        stale_record_no_write,
        "Adapter stale draft-record attempt left draft log and duplicate index unchanged." if stale_record_no_write else "Adapter stale draft-record attempt changed local draft or duplicate records.",
        {
            "draft_log_changed": (
                before_stale_record_snapshot.get("draft_log") != after_stale_record_snapshot.get("draft_log")
                if before_stale_record_snapshot and after_stale_record_snapshot else None
            ),
            "duplicates_changed": (
                before_stale_record_snapshot.get("duplicates") != after_stale_record_snapshot.get("duplicates")
                if before_stale_record_snapshot and after_stale_record_snapshot else None
            ),
        },
    ))
    if not stale_record_no_write:
        return checks

    record_response, error_check = _post_workflow_json(
        caller.post_json,
        caller.url("/api/drafts/record"),
        {
            "payload": draft_payload,
            "draft_id": "draft-adapter-smoke",
            "message_id": "message-adapter-smoke",
            "thread_id": "thread-adapter-smoke",
            "status": "active",
            "notes": "LegalPDF adapter contract smoke record.",
            "gmail_handoff_reviewed": True,
            **prepared_fields,
        },
        "adapter_record_draft",
    )
    if error_check:
        checks.append(error_check)
        return checks
    checks.append(_send_allowed_check(
        "adapter_record_send_allowed",
        record_response,
        "Adapter draft recording keeps send_allowed false.",
    ))
    recorded_duplicate_count = record_response.get("recorded_duplicate_count") if isinstance(record_response, dict) else None
    record_ready = (
        isinstance(record_response, dict)
        and record_response.get("status") == "recorded"
        and record_response.get("draft_id") == "draft-adapter-smoke"
        and bool(record_response.get("message_id"))
        and recorded_duplicate_count == 1
    )
    checks.append(_check(
        "adapter_record_draft",
        record_ready,
        "Adapter smoke recorded the manually-created draft and duplicate blocker in isolated state." if record_ready else "Adapter smoke did not record the draft/duplicate result as expected.",
        {
            "status": record_response.get("status") if isinstance(record_response, dict) else None,
            "draft_id": record_response.get("draft_id") if isinstance(record_response, dict) else None,
            "recorded_duplicate_count": recorded_duplicate_count,
        },
    ))
    return checks


def synthetic_adapter_source(profile: str, case_number: str, service_date: str) -> AdapterSourceInput:
    synthetic_recipient = "court@" + "tribunais.org.pt"
    return AdapterSourceInput(
        profile=profile,
        source_kind="notification_pdf",
        filename="synthetic-notification.pdf",
        content=synthetic_notification_pdf(case_number, service_date, recipient_email=synthetic_recipient),
        content_type="application/pdf",
        expected_case_number=case_number,
        expected_service_date=service_date,
    )


def run_synthetic_adapter_sequence(
    base_url: str,
    *,
    fetch_json: JsonFetcher,
    post_json: PostJsonFetcher,
    post_multipart: PostMultipartFetcher,
    profile: str,
    case_number: str,
    service_date: str,
) -> list[dict[str, Any]]:
    return run_adapter_sequence(
        base_url,
        fetch_json=fetch_json,
        post_json=post_json,
        post_multipart=post_multipart,
        source=synthetic_adapter_source(profile, case_number, service_date),
    )


def run_adapter_sequence_result(
    base_url: str,
    *,
    fetch_json: JsonFetcher,
    post_json: PostJsonFetcher,
    post_multipart: PostMultipartFetcher,
    source: AdapterSourceInput,
) -> AdapterSequenceResult:
    checks = run_adapter_sequence(
        base_url,
        fetch_json=fetch_json,
        post_json=post_json,
        post_multipart=post_multipart,
        source=source,
    )
    return _adapter_sequence_result_from_checks(checks)


def run_synthetic_adapter_sequence_result(
    base_url: str,
    *,
    fetch_json: JsonFetcher,
    post_json: PostJsonFetcher,
    post_multipart: PostMultipartFetcher,
    profile: str,
    case_number: str,
    service_date: str,
) -> AdapterSequenceResult:
    checks = run_synthetic_adapter_sequence(
        base_url,
        fetch_json=fetch_json,
        post_json=post_json,
        post_multipart=post_multipart,
        profile=profile,
        case_number=case_number,
        service_date=service_date,
    )
    return _adapter_sequence_result_from_checks(checks)


def run_synthetic_adapter_sequence_http(
    base_url: str,
    *,
    timeout: float = 5.0,
    profile: str = "example_interpreting",
    case_number: str = "999/26.0SMOKE",
    service_date: str = "2026-05-04",
) -> AdapterSequenceResult:
    caller = build_http_adapter_caller(base_url, timeout=timeout)
    return run_synthetic_adapter_sequence_result(
        caller.base_url,
        fetch_json=caller.fetch_json,
        post_json=caller.post_json,
        post_multipart=caller.post_multipart,
        profile=profile,
        case_number=case_number,
        service_date=service_date,
    )


def run_adapter_sequence_http(
    base_url: str,
    *,
    timeout: float = 5.0,
    source: AdapterSourceInput,
) -> AdapterSequenceResult:
    caller = build_http_adapter_caller(base_url, timeout=timeout)
    return run_adapter_sequence_result(
        caller.base_url,
        fetch_json=caller.fetch_json,
        post_json=caller.post_json,
        post_multipart=caller.post_multipart,
        source=source,
    )


def run_adapter_readiness_http(
    base_url: str,
    *,
    timeout: float = 5.0,
) -> AdapterReadinessResult:
    caller = build_http_adapter_caller(base_url, timeout=timeout)
    return run_adapter_readiness_result(caller.base_url, fetch_json=caller.fetch_json)


def _source_field(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--source-field values must use key=value form.")
    key, field_value = value.split("=", 1)
    key = key.strip()
    if not key:
        raise argparse.ArgumentTypeError("--source-field key must not be empty.")
    return key, field_value


def _source_input_from_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> AdapterSourceInput:
    source_path = Path(str(args.source_file or "")).expanduser()
    if not source_path.exists() or not source_path.is_file():
        parser.error(f"--source-file must point to an existing file: {source_path}")
    try:
        content = source_path.read_bytes()
    except OSError as exc:
        parser.error(f"Could not read --source-file {source_path}: {exc}")
    return AdapterSourceInput(
        profile=args.profile,
        source_kind=args.source_kind,
        filename=args.source_filename or source_path.name,
        content=content,
        expected_case_number=args.case_number,
        expected_service_date=args.service_date,
        content_type=args.content_type,
        visible_metadata_text=args.visible_metadata_text,
        ai_recovery=args.ai_recovery,
        extra_fields=dict(args.source_field or []),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the LegalPDF adapter readiness probe or guarded adapter sequence "
            "against a live app and print a secret-free JSON summary. Use an "
            "isolated synthetic runtime for any full sequence."
        ),
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8766")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--profile", default="example_interpreting")
    parser.add_argument("--case-number", default="999/26.0SMOKE")
    parser.add_argument("--service-date", default="2026-05-04")
    parser.add_argument(
        "--source-file",
        help=(
            "Optional sanitized source file to upload through the generic adapter "
            "sequence instead of the built-in synthetic PDF fixture."
        ),
    )
    parser.add_argument("--source-kind", default="notification_pdf")
    parser.add_argument("--source-filename", help="Optional safe upload filename override.")
    parser.add_argument("--content-type", default="application/pdf")
    parser.add_argument("--visible-metadata-text", default="")
    parser.add_argument("--ai-recovery", default="off")
    parser.add_argument(
        "--source-field",
        action="append",
        type=_source_field,
        default=[],
        metavar="KEY=VALUE",
        help="Additional sanitized upload form field for future adapter callers. Repeatable.",
    )
    parser.add_argument(
        "--readiness-only",
        action="store_true",
        help="Run only the read-only /api/health and adapter-contract readiness probe.",
    )
    parser.add_argument(
        "--allow-synthetic-recording",
        action="store_true",
        help=(
            "Required because the sequence prepares artifacts and records "
            "synthetic draft IDs. Run it against an isolated synthetic runtime."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Accepted for consistency with other smoke helpers; output is always JSON.",
    )
    args = parser.parse_args(argv)
    if args.readiness_only:
        result = run_adapter_readiness_http(args.base_url, timeout=args.timeout)
        print(json.dumps(result.safe_summary(), ensure_ascii=False, indent=2))
        return 0 if result.status == "ready" else 1

    if not args.allow_synthetic_recording:
        parser.error(
            "--allow-synthetic-recording is required because this sequence prepares "
            "artifacts and records synthetic draft IDs; use an isolated synthetic runtime"
        )

    if args.source_file:
        result = run_adapter_sequence_http(
            base_url=args.base_url,
            timeout=args.timeout,
            source=_source_input_from_args(args, parser),
        )
    else:
        result = run_synthetic_adapter_sequence_http(
            args.base_url,
            timeout=args.timeout,
            profile=args.profile,
            case_number=args.case_number,
            service_date=args.service_date,
        )
    print(json.dumps(result.safe_summary(), ensure_ascii=False, indent=2))
    return 0 if result.status == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
