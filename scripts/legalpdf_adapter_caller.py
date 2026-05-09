from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

JsonFetcher = Callable[[str], Any]
PostJsonFetcher = Callable[[str, dict[str, Any]], Any]
PostMultipartFetcher = Callable[[str, dict[str, str], str, bytes, str], Any]

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


@dataclass(frozen=True)
class AdapterContractValidation:
    ready: bool
    send_allowed: bool
    write_allowed: bool
    legalpdf_write_allowed: bool
    missing_endpoints: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def normalize_base_url(base_url: str) -> str:
    value = str(base_url or "").strip()
    if not value:
        raise ValueError("base_url is required")
    if not urllib.parse.urlparse(value).scheme:
        value = f"http://{value}"
    return value.rstrip("/")


def adapter_url(base_url: str, path: str) -> str:
    return f"{normalize_base_url(base_url)}{path}"


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
            and gmail_boundary.get("required_tool") == "_create_draft"
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
