from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # OpenAI is optional at runtime until AI recovery is configured.
    from openai import OpenAI
except Exception:  # pragma: no cover - exercised when dependency is absent locally.
    OpenAI = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AI_CONFIG = ROOT / "config" / "ai.local.json"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
AI_RECOVERY_RESPONSE_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "honorarios_source_recovery",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "raw_visible_text": {
                    "type": "string",
                    "description": "All visible OCR text, preserving useful line breaks. Use an empty string only when no text is visible.",
                },
                "fields": {
                    "type": "object",
                    "properties": {
                        "raw_case_number": {"type": "string"},
                        "case_number": {"type": "string"},
                        "service_date": {"type": "string"},
                        "source_document_timestamp": {"type": "string"},
                        "court_email": {"type": "string"},
                        "payment_entity": {"type": "string"},
                        "service_entity": {"type": "string"},
                        "service_entity_type": {
                            "type": "string",
                            "enum": ["", "court", "ministerio_publico", "gnr", "psp", "police", "other"],
                        },
                        "service_place": {"type": "string"},
                        "service_place_phrase": {"type": "string"},
                        "locality": {"type": "string"},
                        "inspector_or_person": {"type": "string"},
                    },
                    "required": [
                        "raw_case_number",
                        "case_number",
                        "service_date",
                        "source_document_timestamp",
                        "court_email",
                        "payment_entity",
                        "service_entity",
                        "service_entity_type",
                        "service_place",
                        "service_place_phrase",
                        "locality",
                        "inspector_or_person",
                    ],
                    "additionalProperties": False,
                },
                "translation_indicators": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["raw_visible_text", "fields", "translation_indicators", "warnings"],
            "additionalProperties": False,
        },
    }
}
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
CASE_NUMBER_RE = re.compile(r"\b0*\d+/\d{2}\.[A-Z0-9.]+\b", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
EU_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/20\d{2}\b")


@dataclass(slots=True)
class OpenAIConfig:
    configured: bool
    key_source: str = ""
    model: str = DEFAULT_OPENAI_MODEL
    package_available: bool = True


def _read_local_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_openai_config(config_path: Path = DEFAULT_AI_CONFIG, environ: dict[str, str] | None = None) -> OpenAIConfig:
    env = environ if environ is not None else os.environ
    local = _read_local_config(config_path)
    model = str(env.get("HONORARIOS_OPENAI_MODEL") or local.get("model") or DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
    if str(env.get("OPENAI_API_KEY") or "").strip():
        return OpenAIConfig(configured=True, key_source="OPENAI_API_KEY", model=model, package_available=OpenAI is not None)
    if str(local.get("openai_api_key") or local.get("api_key") or "").strip():
        return OpenAIConfig(configured=True, key_source=str(config_path), model=model, package_available=OpenAI is not None)
    return OpenAIConfig(configured=False, key_source="", model=model, package_available=OpenAI is not None)


def resolve_openai_api_key(config_path: Path = DEFAULT_AI_CONFIG, environ: dict[str, str] | None = None) -> str | None:
    env = environ if environ is not None else os.environ
    key = str(env.get("OPENAI_API_KEY") or "").strip()
    if key:
        return key
    local = _read_local_config(config_path)
    key = str(local.get("openai_api_key") or local.get("api_key") or "").strip()
    return key or None


def ai_status_payload(config_path: Path = DEFAULT_AI_CONFIG) -> dict[str, Any]:
    config = resolve_openai_config(config_path)
    return {
        "provider": "openai",
        "configured": bool(config.configured and config.package_available),
        "key_configured": bool(config.configured),
        "package_available": bool(config.package_available),
        "key_source": config.key_source,
        "model": config.model,
        "send_allowed": False,
        "secret_exposed": False,
    }


def text_is_weak_for_pdf_ocr(text: str) -> bool:
    cleaned = (text or "").strip()
    if len(cleaned) < 80:
        return True
    has_case = bool(CASE_NUMBER_RE.search(cleaned))
    has_date = bool(ISO_DATE_RE.search(cleaned) or EU_DATE_RE.search(cleaned))
    return not (has_case and has_date)


def should_attempt_ai_recovery(source_kind: str, mode: str, extracted_text: str) -> bool:
    normalized = (mode or "auto").strip().lower()
    if normalized in {"off", "disabled", "false", "0", "no"}:
        return False
    if normalized in {"always", "force", "on", "true", "1", "yes"}:
        return True
    if source_kind == "photo":
        return True
    if source_kind == "notification_pdf":
        return text_is_weak_for_pdf_ocr(extracted_text)
    return False


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if isinstance(text, str):
                chunks.append(text)
            elif isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(str(content["text"]))
    return "\n".join(chunks).strip()


def _json_from_model_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("AI recovery response was not a JSON object.")
    return data


def _normalize_ai_payload(payload: dict[str, Any]) -> dict[str, Any]:
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    raw_text = str(payload.get("raw_visible_text") or payload.get("visible_text") or payload.get("text") or "").strip()
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    indicators = payload.get("translation_indicators")
    if not isinstance(indicators, list):
        indicators = []
    normalized_fields = {
        str(key): value
        for key, value in fields.items()
        if value not in (None, "", [])
    }
    return {
        "raw_visible_text": raw_text,
        "fields": normalized_fields,
        "translation_indicators": [str(item) for item in indicators if str(item).strip()],
        "warnings": [str(item) for item in warnings if str(item).strip()],
    }


def _prompt_for_source(source_kind: str, deterministic_text: str, source_metadata: dict[str, Any] | None = None) -> str:
    deterministic_hint = deterministic_text.strip()
    if deterministic_hint:
        deterministic_hint = f"\n\nExisting extracted PDF/text layer to cross-check:\n{deterministic_hint[:6000]}"
    metadata_hint = ""
    if source_metadata:
        metadata_hint = "\n\nLocal file/image metadata hints:\n" + json.dumps(source_metadata, ensure_ascii=False, sort_keys=True)[:2000]
    return (
        "You are extracting visible data from Portuguese legal interpretation-service documents for a local fee-request app. "
        "Return strict JSON only. Do not invent missing values. Preserve accents. "
        "If the source looks like translation work or mentions word counts, include those phrases in translation_indicators.\n\n"
        "The uploaded image may be rotated, sideways, cropped, partially visible, or a Google Photos screenshot with a right-side "
        "metadata panel. Inspect all orientations and use visible Google Photos metadata only as photo/capture-date evidence, "
        "not as the service date unless the document text agrees or the service date is otherwise explicit.\n\n"
        "Return this JSON shape:\n"
        "{\n"
        '  "raw_visible_text": "all visible OCR text, preserving useful line breaks",\n'
        '  "fields": {\n'
        '    "raw_case_number": "",\n'
        '    "case_number": "",\n'
        '    "service_date": "YYYY-MM-DD if explicitly visible as service/diligence/metadata date",\n'
        '    "source_document_timestamp": "",\n'
        '    "court_email": "",\n'
        '    "payment_entity": "",\n'
        '    "service_entity": "",\n'
        '    "service_entity_type": "court|ministerio_publico|gnr|psp|police|other if clear",\n'
        '    "service_place": "",\n'
        '    "service_place_phrase": "",\n'
        '    "locality": "",\n'
        '    "inspector_or_person": ""\n'
        "  },\n"
        '  "translation_indicators": [],\n'
        '  "warnings": []\n'
        "}\n\n"
        "Honorários rules: physical service place matters. For Polícia Judiciária, extract the host building and city "
        "such as a GNR post, hospital, or medical-legal office if visible. Do not infer kilometers. "
        f"Source kind: {source_kind}.{metadata_hint}{deterministic_hint}"
    )


def _content_item_for_source(content: bytes, source_kind: str, filename: str, content_type: str) -> dict[str, Any]:
    encoded = base64.b64encode(content).decode("ascii")
    if source_kind == "notification_pdf":
        return {
            "type": "input_file",
            "filename": filename or "source.pdf",
            "file_data": f"data:application/pdf;base64,{encoded}",
        }
    mime = content_type.strip() or "image/jpeg"
    return {
        "type": "input_image",
        "image_url": f"data:{mime};base64,{encoded}",
        "detail": "high",
    }


def _content_items_for_source(
    content: bytes,
    source_kind: str,
    filename: str,
    content_type: str,
    rendered_page_images: list[str] | None = None,
) -> list[dict[str, Any]]:
    if source_kind == "notification_pdf" and rendered_page_images:
        items: list[dict[str, Any]] = []
        for index, path_text in enumerate(rendered_page_images[:3], start=1):
            path = Path(path_text)
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            items.append({
                "type": "input_image",
                "image_url": f"data:image/png;base64,{encoded}",
                "detail": "high",
            })
        return items
    return [_content_item_for_source(content, source_kind, filename, content_type)]


def recover_source_with_openai(
    *,
    filename: str,
    content_type: str,
    content: bytes,
    source_kind: str,
    deterministic_text: str = "",
    mode: str = "auto",
    config_path: Path = DEFAULT_AI_CONFIG,
    source_metadata: dict[str, Any] | None = None,
    rendered_page_images: list[str] | None = None,
) -> dict[str, Any]:
    config = resolve_openai_config(config_path)
    if not should_attempt_ai_recovery(source_kind, mode, deterministic_text):
        return {
            "status": "skipped",
            "attempted": False,
            "configured": bool(config.configured and config.package_available),
            "reason": "AI recovery not needed for this source.",
            "provider": "openai",
            "model": config.model,
            "fields": {},
            "translation_indicators": [],
            "warnings": [],
        }
    if not config.configured:
        return {
            "status": "unconfigured",
            "attempted": False,
            "configured": False,
            "reason": "OPENAI_API_KEY or config/ai.local.json is not configured.",
            "provider": "openai",
            "model": config.model,
            "fields": {},
            "translation_indicators": [],
            "warnings": [],
        }
    if OpenAI is None:
        return {
            "status": "unavailable",
            "attempted": False,
            "configured": False,
            "reason": "The openai Python package is not installed.",
            "provider": "openai",
            "model": config.model,
            "fields": {},
            "translation_indicators": [],
            "warnings": [],
        }

    api_key = resolve_openai_api_key(config_path)
    if not api_key:
        return {
            "status": "unconfigured",
            "attempted": False,
            "configured": False,
            "reason": "OpenAI API key could not be resolved.",
            "provider": "openai",
            "model": config.model,
            "fields": {},
            "translation_indicators": [],
            "warnings": [],
        }

    client = OpenAI(api_key=api_key, max_retries=0)
    prompt = _prompt_for_source(source_kind, deterministic_text, source_metadata)
    source_items = _content_items_for_source(content, source_kind, filename, content_type, rendered_page_images)
    try:
        response = client.responses.create(
            model=config.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        *source_items,
                    ],
                }
            ],
            text=AI_RECOVERY_RESPONSE_FORMAT,
            store=False,
        )
        text = _extract_output_text(response)
        normalized = _normalize_ai_payload(_json_from_model_text(text))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "attempted": True,
            "configured": True,
            "reason": f"OpenAI recovery failed: {exc}",
            "provider": "openai",
            "model": config.model,
            "fields": {},
            "translation_indicators": [],
            "warnings": [],
        }

    if not normalized["raw_visible_text"]:
        return {
            "status": "failed",
            "attempted": True,
            "configured": True,
            "reason": "OpenAI recovery returned no raw visible text; fields were ignored.",
            "provider": "openai",
            "model": config.model,
            "fields": {},
            "translation_indicators": normalized["translation_indicators"],
            "warnings": [*normalized["warnings"], "No raw visible text returned."],
        }

    return {
        "status": "ok",
        "attempted": True,
        "configured": True,
        "reason": "",
        "provider": "openai",
        "model": config.model,
        **normalized,
    }
