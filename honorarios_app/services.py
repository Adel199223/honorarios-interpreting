from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import os
import re
import shutil
import secrets
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from PIL import Image
from pypdf import PdfReader

from scripts.build_email_draft import (
    DEFAULT_COURT_EMAILS,
    DEFAULT_EMAIL_CONFIG,
    build_email_payload,
    resolve_recipient,
    validate_draft_payload,
)
from scripts.build_packet_pdf import PacketError, build_packet_pdf
from scripts.create_intake import DEFAULT_SERVICE_PROFILES, build_intake, current_lisbon_date, load_profiles
from scripts.generate_pdf import (
    BLOCKING_DUPLICATE_STATUSES,
    DEFAULT_DUPLICATE_INDEX,
    DEFAULT_HTML_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROFILE,
    DEFAULT_TEMPLATE,
    IntakeError,
    RenderedRequest,
    build_rendered_request,
    default_output_path,
    duplicate_record_blocks,
    duplicate_record_status,
    find_duplicate_record,
    format_duplicate_message,
    get_service_date_value,
    load_json,
)
from scripts.intake_questions import format_numbered_questions, missing_questions, parse_numbered_answers
from scripts.prepare_honorarios import (
    DEFAULT_DRAFT_LOG,
    DEFAULT_DRAFT_OUTPUT_DIR,
    DEFAULT_MANIFEST_DIR,
    DEFAULT_RENDER_DIR,
    active_drafts_for,
    load_draft_log,
    prepare_one,
    render_png,
    validate_intake_before_generation,
)
from scripts.record_gmail_draft import main as record_gmail_draft_main
from scripts.request_identity import normalize_case_number, request_identity_key
from scripts.source_classification import detect_translation_source, format_translation_rejection

from .ai_recovery import ai_status_payload, recover_source_with_openai, text_is_weak_for_pdf_ocr


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTAKE_OUTPUT_DIR = ROOT / "output" / "intakes"
DEFAULT_SOURCE_UPLOAD_DIR = ROOT / "output" / "source-uploads"
DEFAULT_PACKET_OUTPUT_DIR = ROOT / "output" / "packets"
DEFAULT_BACKUP_OUTPUT_DIR = ROOT / "output" / "backups"
DEFAULT_INTEGRATION_REPORT_OUTPUT_DIR = ROOT / "output" / "integration-reports"
DEFAULT_KNOWN_DESTINATIONS = ROOT / "data" / "known-destinations.json"
DEFAULT_PROFILE_CHANGE_LOG = ROOT / "data" / "profile-change-log.json"
GOOGLE_PHOTOS_PICKER_SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_PHOTOS_PICKER_SESSIONS_URL = "https://photospicker.googleapis.com/v1/sessions"
MAX_SOURCE_UPLOAD_BYTES = 25 * 1024 * 1024
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
PDF_SUFFIXES = {".pdf"}
LIFECYCLE_STATUSES = {"active", "sent", "superseded", "trashed", "not_found"}
ALLOWED_SERVICE_DATE_SOURCES = {
    "document_text",
    "photo_metadata",
    "document_text_and_photo_metadata",
    "user_confirmed",
    "user_confirmed_exception",
    "document_text_user_confirmed",
    "photo_metadata_user_confirmed",
}
ALLOWED_SERVICE_ENTITY_TYPES = {"court", "ministerio_publico", "gnr", "psp", "police", "other"}
CASE_NUMBER_RE = re.compile(r"\b(?:NUIPC|PROCESSO|N[ÚU]MERO\s+DE\s+PROCESSO)?\s*-?\s*:?\s*(0*\d+/\d{2}\.[A-Z0-9.]+)", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
EU_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
COMPACT_DATE_RE = re.compile(r"\b(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:[_-]?\d{6})?\b")
AUTO_PROFILE_VALUES = {"", "auto", "auto_detect", "auto-detect", "court_mp_generic"}


@dataclass(slots=True)
class AppPaths:
    profile: Path = DEFAULT_PROFILE
    template: Path = DEFAULT_TEMPLATE
    service_profiles: Path = DEFAULT_SERVICE_PROFILES
    duplicate_index: Path = DEFAULT_DUPLICATE_INDEX
    email_config: Path = DEFAULT_EMAIL_CONFIG
    court_emails: Path = DEFAULT_COURT_EMAILS
    known_destinations: Path = DEFAULT_KNOWN_DESTINATIONS
    draft_log: Path = DEFAULT_DRAFT_LOG
    profile_change_log: Path = DEFAULT_PROFILE_CHANGE_LOG
    output_dir: Path = DEFAULT_OUTPUT_DIR
    html_dir: Path = DEFAULT_HTML_DIR
    draft_output_dir: Path = DEFAULT_DRAFT_OUTPUT_DIR
    manifest_dir: Path = DEFAULT_MANIFEST_DIR
    render_dir: Path = DEFAULT_RENDER_DIR
    intake_output_dir: Path = DEFAULT_INTAKE_OUTPUT_DIR
    source_upload_dir: Path = DEFAULT_SOURCE_UPLOAD_DIR
    packet_output_dir: Path = DEFAULT_PACKET_OUTPUT_DIR
    backup_output_dir: Path = DEFAULT_BACKUP_OUTPUT_DIR
    integration_report_output_dir: Path = DEFAULT_INTEGRATION_REPORT_OUTPUT_DIR
    ai_config: Path = ROOT / "config" / "ai.local.json"
    google_photos_config: Path = ROOT / "config" / "google-photos.local.json"


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def app_current_date() -> str:
    try:
        return current_lisbon_date()
    except Exception:
        return datetime.now().date().isoformat()


def safe_upload_filename(filename: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename or "source").name).strip(".-")
    return clean or "source"


def _read_json_object_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _configured_value_and_source(
    config: dict[str, Any],
    env_name: str,
    config_name: str,
    config_path: Path,
) -> tuple[str, str]:
    env_value = str(os.environ.get(env_name) or "").strip()
    if env_value:
        return env_value, env_name
    config_value = str(config.get(config_name) or "").strip()
    if config_value:
        return config_value, str(config_path)
    return "", ""


def _google_photos_config(config_path: Path) -> dict[str, Any]:
    config = _read_json_object_if_exists(config_path)
    client_id, client_id_source = _configured_value_and_source(
        config,
        "GOOGLE_PHOTOS_CLIENT_ID",
        "client_id",
        config_path,
    )
    client_secret, client_secret_source = _configured_value_and_source(
        config,
        "GOOGLE_PHOTOS_CLIENT_SECRET",
        "client_secret",
        config_path,
    )
    token_path_text, token_path_source = _configured_value_and_source(
        config,
        "GOOGLE_PHOTOS_TOKEN_PATH",
        "token_path",
        config_path,
    )
    redirect_uri, redirect_uri_source = _configured_value_and_source(
        config,
        "GOOGLE_PHOTOS_REDIRECT_URI",
        "redirect_uri",
        config_path,
    )
    token_path = Path(token_path_text).expanduser() if token_path_text else config_path.with_name("google-photos-token.local.json")
    return {
        "client_id": client_id,
        "client_id_source": client_id_source,
        "client_secret": client_secret,
        "client_secret_source": client_secret_source,
        "token_path": token_path,
        "token_path_source": token_path_source or "default_local",
        "redirect_uri": redirect_uri or "http://127.0.0.1:8766/api/google-photos/oauth/callback",
        "redirect_uri_source": redirect_uri_source or "default_local",
    }


def _read_google_photos_token(token_path: Path) -> dict[str, Any]:
    if not token_path.exists():
        return {}
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_google_photos_token(token_path: Path, token: dict[str, Any]) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(token, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _google_photos_access_token(paths: AppPaths) -> tuple[str, dict[str, Any]]:
    config = _google_photos_config(paths.google_photos_config)
    token = _read_google_photos_token(config["token_path"])
    access_token = str(token.get("access_token") or "").strip()
    if access_token and not _token_expired(token):
        return access_token, token
    refresh_token = str(token.get("refresh_token") or "").strip()
    if refresh_token and config["client_id"] and config["client_secret"]:
        refreshed = _exchange_google_token({
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        token.update(refreshed)
        if "refresh_token" not in token:
            token["refresh_token"] = refresh_token
        _write_google_photos_token(config["token_path"], token)
        access_token = str(token.get("access_token") or "").strip()
        if access_token:
            return access_token, token
    raise IntakeError("Google Photos Picker is not connected. Connect OAuth first or use selected-photo local import.")


def _token_expired(token: dict[str, Any]) -> bool:
    expires_at = str(token.get("expires_at") or "").strip()
    if not expires_at:
        return False
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc) + timedelta(seconds=60)


def _exchange_google_token(form: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        response = client.post(GOOGLE_OAUTH_TOKEN_URL, data=form)
        response.raise_for_status()
        payload = response.json()
    output = dict(payload)
    expires_in = int(output.get("expires_in") or 0)
    if expires_in:
        output["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    return output


def google_photos_status_payload(config_path: Path) -> dict[str, Any]:
    config = _google_photos_config(config_path)
    token_store_present = False
    access_token_present = False
    refresh_token_present = False
    try:
        token_store_present = config["token_path"].exists()
        token = _read_google_photos_token(config["token_path"])
        access_token_present = bool(token.get("access_token"))
        refresh_token_present = bool(token.get("refresh_token"))
    except OSError:
        token_store_present = False
    configured = bool(config["client_id"] and config["client_secret"])
    connected = bool(configured and token_store_present and (access_token_present or refresh_token_present))
    return {
        "provider": "google_photos",
        "scope": GOOGLE_PHOTOS_PICKER_SCOPE,
        "configured": configured,
        "connected": connected,
        "manual_import_ready": True,
        "oauth_picker_ready": connected,
        "client_id_source": config["client_id_source"],
        "client_secret_configured": bool(config["client_secret"]),
        "client_secret_source": config["client_secret_source"],
        "redirect_uri_source": config["redirect_uri_source"],
        "token_store_configured": True,
        "token_store_present": token_store_present,
        "access_token_present": access_token_present,
        "refresh_token_present": refresh_token_present,
        "token_path_source": config["token_path_source"],
        "message": (
            "Google Photos OAuth Picker is connected."
            if connected
            else "OAuth Picker is not connected in this standalone app yet; use selected-photo import with local image metadata."
        ),
        "send_allowed": False,
    }


def google_photos_oauth_start(paths: AppPaths) -> dict[str, Any]:
    config = _google_photos_config(paths.google_photos_config)
    if not config["client_id"] or not config["client_secret"]:
        raise IntakeError("Google Photos OAuth needs GOOGLE_PHOTOS_CLIENT_ID and GOOGLE_PHOTOS_CLIENT_SECRET or config/google-photos.local.json.")
    state = secrets.token_urlsafe(24)
    token = _read_google_photos_token(config["token_path"])
    token.update({
        "oauth_state": state,
        "oauth_started_at": datetime.now(timezone.utc).isoformat(),
        "scope": GOOGLE_PHOTOS_PICKER_SCOPE,
    })
    _write_google_photos_token(config["token_path"], token)
    query = urlencode({
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": GOOGLE_PHOTOS_PICKER_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return {
        "status": "authorization_ready",
        "authorization_url": f"{GOOGLE_OAUTH_AUTH_URL}?{query}",
        "state": state,
        "scope": GOOGLE_PHOTOS_PICKER_SCOPE,
        "redirect_uri_source": config["redirect_uri_source"],
        "send_allowed": False,
    }


def google_photos_oauth_callback(*, code: str, state: str, paths: AppPaths) -> dict[str, Any]:
    config = _google_photos_config(paths.google_photos_config)
    token = _read_google_photos_token(config["token_path"])
    expected_state = str(token.get("oauth_state") or "").strip()
    if not expected_state or state != expected_state:
        raise IntakeError("Google Photos OAuth state mismatch. Start the OAuth flow again.")
    if not code:
        raise IntakeError("Google Photos OAuth callback is missing an authorization code.")
    exchanged = _exchange_google_token({
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": config["redirect_uri"],
    })
    stored = {
        **{key: value for key, value in token.items() if key.startswith("oauth_")},
        **exchanged,
        "connected_at": datetime.now(timezone.utc).isoformat(),
        "scope": exchanged.get("scope") or GOOGLE_PHOTOS_PICKER_SCOPE,
    }
    _write_google_photos_token(config["token_path"], stored)
    return {
        "status": "connected",
        "provider": "google_photos",
        "connected": True,
        "scope": stored["scope"],
        "token_store_present": True,
        "send_allowed": False,
    }


def google_photos_create_picker_session(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    access_token, _token = _google_photos_access_token(paths)
    max_items = int(payload.get("max_items") or 1)
    request_body = {
        "pickingConfig": {
            "maxItemCount": max(1, min(max_items, 50)),
        }
    }
    with httpx.Client(timeout=30) as client:
        response = client.post(
            GOOGLE_PHOTOS_PICKER_SESSIONS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json=request_body,
        )
        response.raise_for_status()
        data = response.json()
    return {
        "status": "picker_session_created",
        "session_id": data.get("id") or data.get("sessionId") or "",
        "picker_uri": data.get("pickerUri") or data.get("picker_uri") or "",
        "polling_config": data.get("pollingConfig") or {},
        "send_allowed": False,
    }


def _extract_media_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("mediaItems") or payload.get("media_items") or payload.get("pickedMediaItems") or []
    return items if isinstance(items, list) else []


def _media_file_info(item: dict[str, Any]) -> dict[str, str]:
    media_file = item.get("mediaFile") or item.get("media_file") or item
    return {
        "id": str(item.get("id") or item.get("mediaItemId") or media_file.get("id") or "google-photo"),
        "filename": str(media_file.get("filename") or media_file.get("fileName") or item.get("filename") or "google-photo.jpg"),
        "mime_type": str(media_file.get("mimeType") or media_file.get("mime_type") or item.get("mimeType") or "image/jpeg"),
        "base_url": str(media_file.get("baseUrl") or media_file.get("base_url") or item.get("baseUrl") or ""),
    }


def google_photos_list_session_media(session_id: str, paths: AppPaths) -> dict[str, Any]:
    access_token, _token = _google_photos_access_token(paths)
    safe_session_id = str(session_id or "").strip()
    if not safe_session_id:
        raise IntakeError("Google Photos Picker session ID is required.")
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{GOOGLE_PHOTOS_PICKER_SESSIONS_URL}/{safe_session_id}/mediaItems",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        data = response.json()
    items = [_media_file_info(item) for item in _extract_media_items(data)]
    return {
        "status": "media_items_ready" if items else "waiting_for_selection",
        "session_id": safe_session_id,
        "selected_count": len(items),
        "items": [
            {"id": item["id"], "filename": item["filename"], "mime_type": item["mime_type"]}
            for item in items
        ],
        "send_allowed": False,
    }


def google_photos_import_selected(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    access_token, _token = _google_photos_access_token(paths)
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise IntakeError("Google Photos Picker session ID is required.")
    with httpx.Client(timeout=30) as client:
        media_response = client.get(
            f"{GOOGLE_PHOTOS_PICKER_SESSIONS_URL}/{session_id}/mediaItems",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        media_response.raise_for_status()
        media_payload = media_response.json()
        items = [_media_file_info(item) for item in _extract_media_items(media_payload)]
        if not items:
            raise IntakeError("No selected Google Photos media item is available yet.")
        selected = items[0]
        if not selected["base_url"]:
            raise IntakeError("Selected Google Photos media item does not include a downloadable base URL.")
        download_url = selected["base_url"]
        if not download_url.endswith("=d"):
            download_url = f"{download_url}=d"
        download_response = client.get(download_url, headers={"Authorization": f"Bearer {access_token}"})
        download_response.raise_for_status()
        content = download_response.content
        content_type = download_response.headers.get("content-type") or selected["mime_type"] or "image/jpeg"

    visible_text = "\n".join(
        part
        for part in [
            selected["filename"],
            str(payload.get("visible_metadata_text") or "").strip(),
        ]
        if part
    )
    result = recover_source_upload(
        filename=selected["filename"],
        content_type=content_type,
        content=content,
        source_kind="photo",
        profile_name=str(payload.get("profile") or ""),
        visible_text=visible_text,
        ai_recovery_mode=str(payload.get("ai_recovery") or "auto"),
        paths=paths,
    )
    result["google_photos"] = {
        "session_id": session_id,
        "selected_count": len(items),
        "imported_filename": selected["filename"],
        "imported_mime_type": selected["mime_type"],
    }
    result["send_allowed"] = False
    return result


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_exif_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def extract_first_date(text: str) -> str:
    iso = ISO_DATE_RE.search(text)
    if iso:
        return iso.group(1)
    eu = EU_DATE_RE.search(text)
    if not eu:
        return ""
    day, month, year = eu.groups()
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return ""


def extract_visible_metadata_date(text: str) -> str:
    compact = COMPACT_DATE_RE.search(text or "")
    if not compact:
        return ""
    year, month, day = compact.groups()
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return ""


def extract_candidate_fields(text: str, paths: AppPaths) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    source_text = text or ""
    case_match = CASE_NUMBER_RE.search(source_text)
    if case_match:
        raw_case = case_match.group(1).strip().upper()
        fields["raw_case_number"] = raw_case
        fields["source_case_number"] = raw_case
        fields["case_number"] = normalize_case_number(raw_case)

    service_date = extract_first_date(source_text)
    if service_date:
        fields["service_date"] = service_date
        fields["service_date_source"] = "document_text"

    email_match = EMAIL_RE.search(source_text)
    if email_match:
        fields["recipient_email"] = email_match.group(0).lower()

    if paths.known_destinations.exists():
        try:
            destinations = load_known_destinations(paths)
        except (IntakeError, json.JSONDecodeError):
            destinations = []
        normalized_text = source_text.casefold()
        for destination in destinations if isinstance(destinations, list) else []:
            examples = [destination.get("destination", ""), *(destination.get("institution_examples") or [])]
            for example in examples:
                if example and str(example).casefold() in normalized_text:
                    fields.setdefault("service_place", str(example))
                    fields.setdefault("transport_destination", str(destination.get("destination") or example))
                    if destination.get("km_one_way") not in (None, ""):
                        fields.setdefault("km_one_way", destination.get("km_one_way"))
                    return fields
    return fields


def combine_text_parts(*parts: str) -> str:
    seen: set[str] = set()
    output: list[str] = []
    for part in parts:
        cleaned = str(part or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return "\n\n".join(output)


def fold_match_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _ai_recovery_text(ai_recovery: dict[str, Any]) -> str:
    if not isinstance(ai_recovery, dict):
        return ""
    parts: list[str] = [str(ai_recovery.get("raw_visible_text") or "")]
    fields = ai_recovery.get("fields")
    if isinstance(fields, dict):
        parts.extend(str(value) for value in fields.values() if value not in (None, ""))
    indicators = ai_recovery.get("translation_indicators")
    if isinstance(indicators, list):
        parts.extend(str(item) for item in indicators if str(item).strip())
    return combine_text_parts(*parts)


def _profile_signal_decision(evidence_text: str) -> dict[str, Any]:
    text = fold_match_text(evidence_text)
    signals: list[str] = []

    def has_any(*needles: str) -> bool:
        matched = [needle for needle in needles if fold_match_text(needle) in text]
        signals.extend(matched)
        return bool(matched)

    has_pj = has_any("policia judiciaria", "diretoria do sul", "inspetor", "inspector")
    has_gnr = has_any("guarda nacional republicana", "gnr", "posto territorial", "posto da gnr", "destacamento")
    has_trabalho = has_any("tribunal do trabalho", "juizo do trabalho", "juízo do trabalho", "litigios laborais", "litígios laborais")
    has_medico = has_any("gabinete medico-legal", "gabinete médico-legal", "hospital jose joaquim fernandes", "medicina legal", "pericia medico", "perícia médico", "vitima", "vítima")
    has_ferreira = has_any("ferreira do alentejo", "gafal")
    has_beja = has_any("posto da gnr de beja", "gnr de beja", "ministerio publico de beja", "ministério público de beja", "jafar")
    has_serpa = has_any("posto territorial de serpa", "serpa", "gdsrp")
    has_beringel = has_any("beringel", "berinjel", "gcbja")
    has_cuba = has_any("posto territorial da gnr de cuba", "gnr de cuba", "gacub")

    if has_pj and has_medico:
        return {"profile_key": "pj_medico_legal_beja", "confidence": "high", "reason": "Polícia Judiciária evidence mentions a medical-legal/hospital service.", "signals": signals}
    if has_pj and has_gnr and has_ferreira:
        return {"profile_key": "pj_gnr_ferreira", "confidence": "high", "reason": "Polícia Judiciária evidence mentions the GNR host building in Ferreira do Alentejo.", "signals": signals}
    if has_pj and has_gnr and has_beja:
        return {"profile_key": "pj_gnr_beja", "confidence": "high", "reason": "Polícia Judiciária evidence mentions the GNR host building in Beja.", "signals": signals}
    if has_trabalho:
        return {"profile_key": "beja_trabalho", "confidence": "high", "reason": "Evidence points to the Tribunal/Juízo do Trabalho de Beja.", "signals": signals}
    if has_gnr and has_beringel:
        return {"profile_key": "gnr_beringel_beja_mp", "confidence": "high", "reason": "GNR evidence mentions Beringel, which uses Beja Ministério Público payment.", "signals": signals}
    if has_gnr and has_ferreira:
        return {"profile_key": "gnr_ferreira_falentejo", "confidence": "high", "reason": "GNR evidence mentions Ferreira do Alentejo without Polícia Judiciária context.", "signals": signals}
    if has_gnr and has_serpa:
        return {"profile_key": "gnr_serpa_judicial", "confidence": "high", "reason": "GNR evidence mentions Serpa.", "signals": signals}
    if has_gnr and has_cuba:
        return {"profile_key": "gnr_cuba", "confidence": "high", "reason": "GNR evidence mentions Cuba.", "signals": signals}
    return {"profile_key": "", "confidence": "low", "reason": "No confident service-profile match was found.", "signals": signals}


def choose_service_profile(
    *,
    requested_profile: str,
    extracted_text: str,
    ai_recovery: dict[str, Any],
    profiles: dict[str, Any],
) -> dict[str, Any]:
    requested = str(requested_profile or "").strip()
    evidence_text = combine_text_parts(extracted_text, _ai_recovery_text(ai_recovery))
    suggestion = _profile_signal_decision(evidence_text)
    suggested_key = str(suggestion.get("profile_key") or "").strip()
    suggested_is_available = suggested_key in profiles
    requested_is_auto = requested.casefold() in AUTO_PROFILE_VALUES

    if requested and not requested_is_auto:
        return {
            "mode": "explicit_profile",
            "profile_key": requested,
            "requested_profile": requested,
            "suggested_profile_key": suggested_key if suggested_is_available else "",
            "confidence": suggestion.get("confidence", "low"),
            "reason": "User-selected profile kept; automatic profile selection did not override it.",
            "suggestion_reason": suggestion.get("reason", ""),
            "signals": suggestion.get("signals", []),
            "auto_applied": False,
        }

    if suggested_is_available and suggestion.get("confidence") == "high":
        return {
            "mode": "auto_applied",
            "profile_key": suggested_key,
            "requested_profile": requested,
            "suggested_profile_key": suggested_key,
            "confidence": "high",
            "reason": suggestion.get("reason", ""),
            "signals": suggestion.get("signals", []),
            "auto_applied": True,
        }

    return {
        "mode": "auto_fallback",
        "profile_key": "court_mp_generic",
        "requested_profile": requested,
        "suggested_profile_key": suggested_key if suggested_is_available else "",
        "confidence": suggestion.get("confidence", "low"),
        "reason": suggestion.get("reason", "No confident service-profile match was found."),
        "signals": suggestion.get("signals", []),
        "auto_applied": False,
    }


def slug_token(value: Any) -> str:
    text = fold_match_text(value)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def _profile_locality(candidate: dict[str, Any]) -> str:
    ai_locality = _first_ai_field(candidate.get("ai_recovery") or {}, "locality", "city")
    if ai_locality:
        return ai_locality
    place = str(candidate.get("service_place") or "").strip()
    replacements = [
        r"^posto\s+territorial\s+(?:da\s+)?(?:gnr\s+)?(?:de|do|da)\s+",
        r"^posto\s+da\s+gnr\s+(?:de|do|da)\s+",
        r"^esquadra\s+(?:da\s+)?psp\s+(?:de|do|da)\s+",
        r"^tribunal\s+(?:judicial\s+)?(?:de|do|da)\s+",
    ]
    folded = fold_match_text(place)
    for pattern in replacements:
        cleaned = re.sub(pattern, "", folded).strip()
        if cleaned != folded and cleaned:
            return cleaned.title()
    return place


def _payment_suffix(payment_entity: str, recipient_email: str) -> str:
    payment = fold_match_text(payment_entity)
    recipient = fold_match_text(recipient_email)
    if "ministerio publico de beja" in payment or recipient.startswith("beja.ministeriopublico"):
        return "beja_mp"
    if "trabalho" in payment or "trabalho" in recipient:
        return "beja_trabalho"
    if "serpa" in payment or recipient.startswith("serpa."):
        return "serpa_judicial"
    if "ferreira do alentejo" in payment or recipient.startswith("falentejo."):
        return "falentejo_judicial"
    if "cuba" in payment or recipient.startswith("cuba."):
        return "cuba_judicial"
    token = slug_token(payment_entity or recipient_email)
    return token or "payment_pending"


def _default_addressee(payment_entity: str) -> str:
    entity = str(payment_entity or "").strip()
    if not entity:
        return ""
    if "procurador" in fold_match_text(entity):
        return entity
    return f"Exmo. Senhor Procurador da República\n{entity}"


def build_profile_proposal(candidate: dict[str, Any], profile_decision: dict[str, Any], profiles: dict[str, Any]) -> dict[str, Any]:
    if profile_decision.get("auto_applied"):
        return {
            "status": "not_needed",
            "reason": "A known service profile was auto-applied.",
            "send_allowed": False,
        }
    if profile_decision.get("mode") == "explicit_profile":
        return {
            "status": "not_needed",
            "reason": "A user-selected service profile is already in use.",
            "send_allowed": False,
        }

    service_place = str(candidate.get("service_place") or "").strip()
    service_entity_type = str(candidate.get("service_entity_type") or "").strip() or "other"
    payment_entity = str(candidate.get("payment_entity") or "").strip()
    recipient_email = str(candidate.get("recipient_email") or "").strip().lower()
    service_entity = str(candidate.get("service_entity") or "").strip()
    locality = _profile_locality(candidate).strip()
    ai_recovery = candidate.get("ai_recovery") or {}
    ai_km = _first_ai_field(ai_recovery, "km_one_way", "transport_km_one_way", "one_way_km")
    existing_transport = candidate.get("transport") if isinstance(candidate.get("transport"), dict) else {}
    km_one_way = existing_transport.get("km_one_way") or ai_km

    missing = []
    if not service_place:
        missing.append("service_place")
    if not payment_entity:
        missing.append("payment_entity")
    if not recipient_email:
        missing.append("recipient_email")
    if not locality:
        missing.append("transport_destination")
    if km_one_way in (None, ""):
        missing.append("km_one_way")

    if not service_place and not service_entity and not payment_entity:
        return {
            "status": "insufficient",
            "reason": "Not enough recovered evidence to propose a reusable profile.",
            "missing": missing,
            "send_allowed": False,
        }

    has_pj = "policia judiciaria" in fold_match_text(combine_text_parts(service_entity, str(candidate.get("source_text") or "")))
    prefix = "pj" if has_pj else slug_token(service_entity_type or "service")
    place_slug = slug_token(locality or service_place or service_entity)
    payment_slug = _payment_suffix(payment_entity, recipient_email)
    key_parts = [part for part in [prefix, place_slug, payment_slug] if part]
    profile_key = "_".join(key_parts) or "new_interpreting_profile"
    if not re.match(r"^[a-z]", profile_key):
        profile_key = f"profile_{profile_key}"
    original_key = profile_key
    suffix = 2
    while profile_key in profiles:
        profile_key = f"{original_key}_{suffix}"
        suffix += 1

    phrase = str(candidate.get("service_place_phrase") or "").strip()
    if not phrase and service_place:
        if has_pj:
            phrase = f"em diligência da Polícia Judiciária realizada em {service_place}"
        elif service_entity_type == "gnr":
            phrase = f"em diligência da Guarda Nacional Republicana realizada em {service_place}"
        elif service_entity_type == "psp":
            phrase = f"em diligência da Polícia de Segurança Pública realizada em {service_place}"
        else:
            phrase = f"em diligência realizada em {service_place}"

    payload: dict[str, Any] = {
        "key": profile_key,
        "description": f"Proposed reusable profile for {service_place or service_entity or payment_entity}.",
        "service_date_source": str(candidate.get("service_date_source") or "user_confirmed"),
        "addressee": _default_addressee(payment_entity),
        "payment_entity": payment_entity,
        "recipient_email": recipient_email,
        "service_entity": service_entity,
        "service_entity_type": service_entity_type,
        "entities_differ": bool(candidate.get("entities_differ", service_entity_type in {"gnr", "psp", "police", "other"})),
        "service_place": service_place,
        "service_place_phrase": phrase,
        "claim_transport": bool(candidate.get("claim_transport", True)),
        "transport_destination": locality or service_place,
        "km_one_way": int(km_one_way) if str(km_one_way or "").isdigit() else km_one_way,
        "closing_city": str(candidate.get("closing_city") or locality or payment_entity or "").strip(),
        "source_text_template": f"Serviço de interpretação em {{service_date}}, no âmbito do NUIPC {{case_number}}, {phrase or 'no local de serviço indicado'}.",
        "notes_template": "Created from an app-proposed service profile. Review recipient, kilometers, and service-place wording before saving.",
        "change_reason": "Proposed from uploaded source evidence; review before saving.",
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "")}
    return {
        "status": "proposed" if not missing else "needs_review",
        "reason": "No known profile matched, so the app proposed a guarded reusable profile from recovered evidence.",
        "missing": missing,
        "payload": payload,
        "preview_endpoint": "/api/reference/service-profiles/preview",
        "save_endpoint": "/api/reference/service-profiles",
        "send_allowed": False,
    }


def _first_ai_field(ai_recovery: dict[str, Any], *names: str) -> str:
    fields = ai_recovery.get("fields") if isinstance(ai_recovery, dict) else {}
    if not isinstance(fields, dict):
        return ""
    for name in names:
        value = str(fields.get(name) or "").strip()
        if value:
            return value
    return ""


def _looks_like_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(value.strip()))


def _looks_like_iso_date(value: str) -> bool:
    try:
        datetime.strptime(value.strip(), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _service_date_source_for_ai(intake: dict[str, Any], date: str) -> str:
    metadata_date = str(intake.get("photo_metadata_date") or "").strip()
    if metadata_date and metadata_date == date:
        return "document_text_and_photo_metadata"
    return "document_text"


def _safe_ai_recovery_for_intake(ai_recovery: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "status",
        "attempted",
        "configured",
        "reason",
        "provider",
        "model",
        "raw_visible_text",
        "fields",
        "translation_indicators",
        "warnings",
    ]
    return {key: copy.deepcopy(ai_recovery.get(key)) for key in keys if key in ai_recovery}


def merge_ai_recovery_into_intake(intake: dict[str, Any], ai_recovery: dict[str, Any]) -> dict[str, Any]:
    if not ai_recovery:
        return intake
    intake["ai_recovery"] = _safe_ai_recovery_for_intake(ai_recovery)
    if ai_recovery.get("status") != "ok":
        return intake

    raw_visible_text = str(ai_recovery.get("raw_visible_text") or "").strip()
    if raw_visible_text:
        intake["source_text"] = combine_text_parts(str(intake.get("source_text") or ""), raw_visible_text)

    raw_case = _first_ai_field(ai_recovery, "raw_case_number", "source_case_number", "case_number").upper()
    if raw_case and not intake.get("case_number"):
        intake["raw_case_number"] = raw_case
        intake["source_case_number"] = raw_case
        intake["case_number"] = normalize_case_number(raw_case)

    service_date = _first_ai_field(ai_recovery, "service_date")
    if service_date and _looks_like_iso_date(service_date) and not intake.get("service_date"):
        intake["service_date"] = service_date
        intake["service_date_source"] = _service_date_source_for_ai(intake, service_date)

    source_timestamp = _first_ai_field(ai_recovery, "source_document_timestamp", "document_timestamp")
    if source_timestamp and not intake.get("source_document_timestamp"):
        intake["source_document_timestamp"] = source_timestamp

    court_email = _first_ai_field(ai_recovery, "court_email", "recipient_email")
    if court_email and _looks_like_email(court_email):
        raw_text = raw_visible_text.casefold()
        existing_email = str(intake.get("recipient_email") or "").strip()
        if not existing_email or court_email.casefold() in raw_text:
            intake["recipient_email"] = court_email.lower()

    fill_if_missing = {
        "payment_entity": _first_ai_field(ai_recovery, "payment_entity"),
        "service_entity": _first_ai_field(ai_recovery, "service_entity"),
        "service_entity_type": _first_ai_field(ai_recovery, "service_entity_type"),
        "service_place": _first_ai_field(ai_recovery, "service_place", "locality"),
        "service_place_phrase": _first_ai_field(ai_recovery, "service_place_phrase"),
    }
    for key, value in fill_if_missing.items():
        existing_value = str(intake.get(key) or "").strip()
        if key == "service_entity_type" and value and existing_value == "court" and value in {"gnr", "psp", "police", "other"}:
            intake[key] = value
        elif value and not existing_value:
            intake[key] = value

    entity_type = str(intake.get("service_entity_type") or "").strip().casefold()
    if entity_type in {"gnr", "psp", "police", "other"}:
        intake["entities_differ"] = True

    inspector = _first_ai_field(ai_recovery, "inspector_or_person", "inspector")
    if inspector:
        existing_notes = str(intake.get("notes") or "").strip()
        note = f"AI recovery saw inspector/person context: {inspector}."
        intake["notes"] = combine_text_parts(existing_notes, note)

    return intake


def image_metadata_from_bytes(content: bytes) -> dict[str, Any]:
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            metadata: dict[str, Any] = {
                "width": image.width,
                "height": image.height,
                "format": image.format or "",
            }
            exif = image.getexif()
            orientation = exif.get(274)
            if orientation not in (None, ""):
                metadata["exif_orientation"] = int(orientation)
            for tag in (36867, 36868, 306):
                exif_date = parse_exif_date(exif.get(tag))
                if exif_date:
                    metadata["exif_date"] = exif_date
                    break
            warnings: list[str] = []
            min_side = min(image.width, image.height)
            max_side = max(image.width, image.height)
            if min_side < 320:
                warnings.append("Image is very narrow or small; the legal document may be cropped or only partially visible.")
            if min_side and max_side / min_side > 3:
                warnings.append("Image aspect ratio is unusually narrow or wide; inspect for cropped or partial document content.")
            if orientation not in (None, 1, ""):
                warnings.append("Image has EXIF orientation metadata; verify the visible text direction before generating.")
            if warnings:
                metadata["warnings"] = warnings
            return metadata
    except OSError as exc:
        raise IntakeError("Uploaded photo/screenshot is not a readable image.") from exc


def pdf_text_from_bytes(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
        pages = []
        for page in reader.pages[:8]:
            pages.append(page.extract_text() or "")
        return "\n".join(pages).strip()
    except Exception as exc:  # pypdf raises several parser-specific exceptions.
        raise IntakeError("Uploaded notification PDF could not be read.") from exc


def render_pdf_pages_for_source(pdf_path: Path, *, max_pages: int = 3) -> tuple[list[Path], list[str]]:
    warnings: list[str] = []
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        return [], ["pdftoppm is not available; weak/scanned PDF page images could not be rendered for preview or AI recovery."]
    prefix = pdf_path.parent / f"{pdf_path.stem}_page"
    try:
        result = subprocess.run(
            [pdftoppm, "-png", "-f", "1", "-l", str(max_pages), str(pdf_path), str(prefix)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return [], [f"pdftoppm could not render weak/scanned PDF pages: {exc}"]
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown renderer error"
        return [], [f"pdftoppm could not render weak/scanned PDF pages: {detail}"]
    paths = sorted(pdf_path.parent.glob(f"{prefix.name}-*.png"))
    if not paths:
        warnings.append("pdftoppm rendered no page images for this weak/scanned PDF.")
    return paths, warnings


def validate_upload(source_kind: str, filename: str, content_type: str, content: bytes) -> str:
    if source_kind not in {"notification_pdf", "photo"}:
        raise IntakeError("source_kind must be notification_pdf or photo.")
    if not content:
        raise IntakeError("Uploaded file is empty.")
    if len(content) > MAX_SOURCE_UPLOAD_BYTES:
        raise IntakeError("Uploaded file is too large.")
    suffix = Path(filename or "").suffix.lower()
    if source_kind == "notification_pdf":
        if suffix not in PDF_SUFFIXES and content_type != "application/pdf":
            raise IntakeError("Notification PDF upload must be a PDF file.")
        if not content.lstrip().startswith(b"%PDF"):
            raise IntakeError("Notification PDF upload is not a valid PDF file.")
        return suffix or ".pdf"
    if suffix not in IMAGE_SUFFIXES and not content_type.startswith("image/"):
        raise IntakeError("Photo/Screenshot upload must be an image file.")
    image_metadata_from_bytes(content)
    return suffix or mimetypes.guess_extension(content_type) or ".jpg"


def artifact_root(root_key: str, paths: AppPaths) -> Path:
    roots = {
        "sources": paths.source_upload_dir,
        "renders": paths.render_dir,
    }
    root = roots.get(root_key)
    if not root:
        raise IntakeError("Unknown artifact root.")
    return root.resolve()


def artifact_url_for_path(path: str | Path, paths: AppPaths) -> str:
    resolved = Path(path).resolve()
    for root_key in ("sources", "renders"):
        root = artifact_root(root_key, paths)
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        return f"/api/artifacts/{root_key}/{relative.as_posix()}"
    return ""


def resolve_artifact_path(root_key: str, relative_path: str, paths: AppPaths) -> Path:
    root = artifact_root(root_key, paths)
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise IntakeError("Artifact path is outside the allowed output folder.") from exc
    if not target.exists() or not target.is_file():
        raise IntakeError("Artifact was not found.")
    return target


def build_partial_intake_from_profile(
    *,
    profile_name: str,
    source_kind: str,
    filename: str,
    stored_path: Path,
    digest: str,
    extracted_text: str,
    metadata: dict[str, Any],
    paths: AppPaths,
) -> dict[str, Any]:
    profiles = load_profiles(paths.service_profiles)
    selected_profile = profile_name or "court_mp_generic"
    profile = profiles.get(selected_profile)
    if not isinstance(profile, dict):
        available = ", ".join(sorted(profiles))
        raise IntakeError(f"Unknown service profile {selected_profile!r}. Available profiles: {available}")

    defaults = profile.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise IntakeError(f"Profile defaults must be an object: {selected_profile}")
    intake = copy.deepcopy(defaults)
    intake["closing_date"] = app_current_date()
    intake["source_filename"] = filename
    intake["source_file"] = str(stored_path.resolve())
    intake["source_kind"] = source_kind
    intake["source_sha256"] = digest
    if extracted_text.strip():
        intake["source_text"] = extracted_text.strip()

    fields = extract_candidate_fields(extracted_text, paths)
    extracted_service_date = str(fields.get("service_date") or "").strip()
    transport_destination = fields.pop("transport_destination", "")
    km_one_way = fields.pop("km_one_way", "")
    for key, value in fields.items():
        if value not in (None, ""):
            intake[key] = value
    if extracted_service_date:
        intake["service_date_source"] = _service_date_source_for_ai(intake, extracted_service_date)
    if transport_destination or km_one_way not in (None, ""):
        transport = copy.deepcopy(intake.get("transport") or {})
        if transport_destination:
            transport["destination"] = transport_destination
        if km_one_way not in (None, ""):
            transport["km_one_way"] = km_one_way
        intake["transport"] = transport

    photo_metadata_date = str(metadata.get("exif_date") or metadata.get("visible_metadata_date") or "").strip()
    if photo_metadata_date:
        intake["photo_metadata_date"] = photo_metadata_date
        if intake.get("service_date") and intake.get("service_date") == photo_metadata_date:
            intake["service_date_source"] = "document_text_and_photo_metadata"
        elif not intake.get("service_date"):
            intake.setdefault("service_date_source", "photo_metadata")

    return intake


def recover_source_upload(
    *,
    filename: str,
    content_type: str,
    content: bytes,
    source_kind: str,
    profile_name: str = "",
    visible_text: str = "",
    ai_recovery_mode: str = "auto",
    paths: AppPaths,
) -> dict[str, Any]:
    suffix = validate_upload(source_kind, filename, content_type or "", content)
    digest = sha256_hex(content)
    safe_name = safe_upload_filename(filename)
    stored_filename = f"{timestamp_slug()}_{digest[:12]}_{safe_name}"
    if not Path(stored_filename).suffix:
        stored_filename = f"{stored_filename}{suffix}"
    stored_path = paths.source_upload_dir / stored_filename
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(content)

    extracted_text = ""
    metadata: dict[str, Any] = {}
    if source_kind == "notification_pdf":
        extracted_text = pdf_text_from_bytes(content)
    else:
        metadata = image_metadata_from_bytes(content)
    if visible_text.strip():
        extracted_text = "\n".join(part for part in [extracted_text, visible_text.strip()] if part)
        visible_metadata_date = extract_visible_metadata_date(visible_text)
        if source_kind == "photo" and visible_metadata_date:
            metadata["visible_metadata_date"] = visible_metadata_date

    rendered_page_paths: list[Path] = []
    if source_kind == "notification_pdf" and text_is_weak_for_pdf_ocr(extracted_text):
        rendered_page_paths, render_warnings = render_pdf_pages_for_source(stored_path)
        metadata["rendered_page_count"] = len(rendered_page_paths)
        if rendered_page_paths:
            metadata["rendered_pages"] = [
                {
                    "path": str(path.resolve()),
                    "artifact_url": artifact_url_for_path(path, paths),
                }
                for path in rendered_page_paths
            ]
            metadata.setdefault("warnings", []).append(
                f"Weak/scanned PDF text layer; using {len(rendered_page_paths)} rendered PDF page image(s) for AI recovery evidence."
            )
        if render_warnings:
            metadata.setdefault("warnings", []).extend(render_warnings)

    ai_recovery = recover_source_with_openai(
        filename=filename,
        content_type=content_type,
        content=content,
        source_kind=source_kind,
        deterministic_text=extracted_text,
        mode=ai_recovery_mode,
        config_path=paths.ai_config,
        source_metadata=metadata,
        rendered_page_images=[str(path.resolve()) for path in rendered_page_paths],
    )
    profiles = load_profiles(paths.service_profiles)
    profile_decision = choose_service_profile(
        requested_profile=profile_name,
        extracted_text=extracted_text,
        ai_recovery=ai_recovery,
        profiles=profiles,
    )
    candidate = build_partial_intake_from_profile(
        profile_name=str(profile_decision.get("profile_key") or "court_mp_generic"),
        source_kind=source_kind,
        filename=filename,
        stored_path=stored_path,
        digest=digest,
        extracted_text=extracted_text,
        metadata=metadata,
        paths=paths,
    )
    candidate = merge_ai_recovery_into_intake(candidate, ai_recovery)
    candidate["auto_profile"] = profile_decision
    profile_proposal = build_profile_proposal(candidate, profile_decision, profiles)
    review = review_intake(candidate, paths)
    combined_text = str(candidate.get("source_text") or extracted_text or "").strip()

    source_warnings = [
        *[str(item) for item in metadata.get("warnings", []) if str(item).strip()],
        *[str(item) for item in ai_recovery.get("warnings", []) if str(item).strip()],
    ]

    return {
        "status": "uploaded",
        "source": {
            "source_kind": source_kind,
            "filename": filename,
            "stored_path": str(stored_path.resolve()),
            "artifact_url": artifact_url_for_path(stored_path, paths),
            "sha256": digest,
            "size": len(content),
            "content_type": content_type,
            "metadata": metadata,
        },
        "extracted_text": combined_text,
        "ai_recovery": ai_recovery,
        "profile_proposal": profile_proposal,
        "candidate_intake": candidate,
        "review": review,
        "source_evidence": {
            "filename": filename,
            "kind": source_kind,
            "case_number": candidate.get("case_number", ""),
            "raw_case_number": candidate.get("raw_case_number", candidate.get("source_case_number", "")),
            "service_date": candidate.get("service_date", ""),
            "photo_metadata_date": candidate.get("photo_metadata_date", ""),
            "recipient_email": candidate.get("recipient_email", ""),
            "service_place": candidate.get("service_place", ""),
            "question_count": len(review.get("questions") or []),
            "ai_status": ai_recovery.get("status", ""),
            "ai_attempted": bool(ai_recovery.get("attempted")),
            "auto_profile": profile_decision,
            "profile_proposal": profile_proposal,
            "warnings": source_warnings,
            "rendered_page_urls": [item["artifact_url"] for item in metadata.get("rendered_pages", [])],
            "rendered_page_count": metadata.get("rendered_page_count", 0),
        },
        "send_allowed": False,
    }


def read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise IntakeError(f"Expected a JSON list at {path}")
    return data


def write_json_list(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_known_destinations(paths: AppPaths) -> list[dict[str, Any]]:
    return read_json_list(paths.known_destinations)


def _coerce_reference_lines(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[\n,]+", str(value))
    output: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _coerce_positive_int(value: Any, *, field: str) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise IntakeError(f"{field} must be a positive whole number.") from exc
    if number <= 0:
        raise IntakeError(f"{field} must be greater than zero.")
    return number


def normalize_destination_record(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    destination = str(payload.get("destination") or payload.get("name") or "").strip()
    if not destination:
        raise IntakeError("destination is required.")
    existing = existing or {}
    km_value = payload.get("km_one_way", payload.get("km", existing.get("km_one_way")))
    km_one_way = _coerce_positive_int(km_value, field="km_one_way")
    examples = _coerce_reference_lines(payload.get("institution_examples"))
    if not examples:
        examples = _coerce_reference_lines(existing.get("institution_examples"))
    notes = str(payload.get("notes", existing.get("notes", "")) or "").strip()
    return {
        "destination": destination,
        "institution_examples": examples,
        "km_one_way": km_one_way,
        "notes": notes,
    }


def upsert_known_destination(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IntakeError("Destination payload must be an object.")
    records = load_known_destinations(paths)
    destination_key = str(payload.get("destination") or payload.get("name") or "").strip().casefold()
    existing_index = next(
        (index for index, record in enumerate(records) if str(record.get("destination") or "").strip().casefold() == destination_key),
        None,
    )
    existing = records[existing_index] if existing_index is not None else None
    record = normalize_destination_record(payload, existing)
    if existing_index is None:
        records.append(record)
    else:
        records[existing_index] = record
    write_json_list(paths.known_destinations, records)
    return {
        "status": "saved",
        "kind": "destination",
        "record": record,
        "count": len(records),
        "send_allowed": False,
    }


def normalize_court_email_record(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    key = str(payload.get("key") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", key):
        raise IntakeError("key is required and must use lowercase letters, numbers, and hyphens.")
    email = str(payload.get("email") or "").strip().lower()
    if not _looks_like_email(email):
        raise IntakeError("email must be a valid email address.")
    existing = existing or {}
    name = str(payload.get("name", existing.get("name", "")) or "").strip()
    if not name:
        raise IntakeError("name is required.")
    aliases = _coerce_reference_lines(payload.get("payment_entity_aliases"))
    if not aliases:
        aliases = _coerce_reference_lines(existing.get("payment_entity_aliases"))
    source = str(payload.get("source", existing.get("source", "")) or "").strip()
    return {
        "key": key,
        "name": name,
        "email": email,
        "payment_entity_aliases": aliases,
        "source": source,
    }


def upsert_court_email(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IntakeError("Court email payload must be an object.")
    records = read_json_list(paths.court_emails)
    key = str(payload.get("key") or "").strip()
    existing_index = next(
        (index for index, record in enumerate(records) if str(record.get("key") or "").strip() == key),
        None,
    )
    existing = records[existing_index] if existing_index is not None else None
    record = normalize_court_email_record(payload, existing)
    if existing_index is None:
        records.append(record)
    else:
        records[existing_index] = record
    write_json_list(paths.court_emails, records)
    return {
        "status": "saved",
        "kind": "court_email",
        "record": record,
        "count": len(records),
        "send_allowed": False,
    }


def write_json_object(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


BACKUP_SCHEMA_VERSION = 1
BACKUP_KIND = "honorarios_local_backup"
BACKUP_RECENT_SECONDS = 24 * 60 * 60


def backup_dataset_paths(paths: AppPaths) -> dict[str, tuple[Path, type]]:
    return {
        "service_profiles": (paths.service_profiles, dict),
        "court_emails": (paths.court_emails, list),
        "known_destinations": (paths.known_destinations, list),
        "duplicate_index": (paths.duplicate_index, list),
        "gmail_draft_log": (paths.draft_log, list),
        "profile_change_log": (paths.profile_change_log, list),
    }


def read_backup_dataset(path: Path, expected_type: type) -> Any:
    if not path.exists():
        return {} if expected_type is dict else []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, expected_type):
        type_name = "object" if expected_type is dict else "list"
        raise IntakeError(f"Expected backup dataset source to be a JSON {type_name}: {path}")
    return data


def backup_counts(datasets: dict[str, Any]) -> dict[str, int]:
    return {
        key: len(value) if isinstance(value, (dict, list)) else 0
        for key, value in datasets.items()
    }


def managed_backup_counts(paths: AppPaths) -> dict[str, int]:
    datasets = {
        key: read_backup_dataset(path, expected_type)
        for key, (path, expected_type) in backup_dataset_paths(paths).items()
    }
    return backup_counts(datasets)


def backup_file_records(paths: AppPaths) -> list[dict[str, Any]]:
    if not paths.backup_output_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in paths.backup_output_dir.glob("*backup-*.json"):
        if not path.is_file():
            continue
        stat = path.stat()
        created_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        prefix = path.name.split("-backup-", 1)[0]
        records.append({
            "path": path,
            "created_at": created_at,
            "size_bytes": stat.st_size,
            "prefix": prefix,
        })
    return sorted(records, key=lambda item: item["created_at"], reverse=True)


def backup_status_payload(paths: AppPaths) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    records = backup_file_records(paths)
    latest = records[0] if records else None
    age_seconds = int((now - latest["created_at"]).total_seconds()) if latest else None
    backup_recommended = latest is None or age_seconds is None or age_seconds > BACKUP_RECENT_SECONDS
    status = "recommended" if backup_recommended else "ready"
    if latest is None:
        message = "No local backup found. Export a backup before high-risk local edits."
    elif backup_recommended:
        message = "Latest local backup is older than 24 hours. Export a fresh backup before high-risk local edits."
    else:
        message = "Recent local backup found. Reference edits and restores have a current rollback point."
    return {
        "status": status,
        "message": message,
        "backup_recommended": backup_recommended,
        "latest_backup_file": str(latest["path"]) if latest else "",
        "latest_backup_created_at": latest["created_at"].isoformat() if latest else "",
        "latest_backup_age_seconds": age_seconds,
        "latest_backup_size_bytes": latest["size_bytes"] if latest else 0,
        "latest_backup_prefix": latest["prefix"] if latest else "",
        "backup_file_count": len(records),
        "managed_counts": managed_backup_counts(paths),
        "recent_threshold_seconds": BACKUP_RECENT_SECONDS,
        "send_allowed": False,
    }


def backup_payload(paths: AppPaths) -> dict[str, Any]:
    datasets = {
        key: read_backup_dataset(path, expected_type)
        for key, (path, expected_type) in backup_dataset_paths(paths).items()
    }
    return {
        "kind": BACKUP_KIND,
        "schema_version": BACKUP_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "datasets": datasets,
        "counts": backup_counts(datasets),
        "contains_private_local_data": True,
        "notes": "Local honorários backup for private app data. Do not publish this file.",
        "send_allowed": False,
    }


def write_backup_file(backup: dict[str, Any], paths: AppPaths, *, prefix: str = "honorarios-backup") -> Path:
    paths.backup_output_dir.mkdir(parents=True, exist_ok=True)
    path = paths.backup_output_dir / f"{prefix}-{timestamp_slug()}-{secrets.token_hex(4)}.json"
    path.write_text(json.dumps(backup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def export_local_backup(paths: AppPaths) -> dict[str, Any]:
    backup = backup_payload(paths)
    backup_file = write_backup_file(backup, paths)
    return {
        "status": "exported",
        "message": "Local backup exported. Keep this file private.",
        "backup_file": str(backup_file),
        "backup": backup,
        "counts": backup["counts"],
        "backup_status": backup_status_payload(paths),
        "send_allowed": False,
    }


def parse_backup_input(payload: dict[str, Any]) -> dict[str, Any]:
    raw_backup = payload.get("backup")
    if raw_backup is None:
        backup_json = str(payload.get("backup_json") or "").strip()
        if not backup_json:
            raise IntakeError("Missing backup JSON.")
        try:
            raw_backup = json.loads(backup_json)
        except json.JSONDecodeError as exc:
            raise IntakeError(f"Backup JSON is invalid: {exc}") from exc
    if not isinstance(raw_backup, dict):
        raise IntakeError("Backup must be a JSON object.")
    return raw_backup


def validate_backup_payload(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    backup = parse_backup_input(payload)
    if backup.get("kind") != BACKUP_KIND:
        raise IntakeError("Backup kind is not supported.")
    if backup.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise IntakeError("Backup schema_version is not supported.")
    datasets = backup.get("datasets")
    if not isinstance(datasets, dict):
        raise IntakeError("Backup must include a datasets object.")

    allowed = backup_dataset_paths(paths)
    unknown = sorted(set(datasets) - set(allowed))
    if unknown:
        raise IntakeError(f"Backup contains unsupported dataset(s): {', '.join(unknown)}")
    if not datasets:
        raise IntakeError("Backup does not contain any restorable datasets.")

    validated: dict[str, Any] = {}
    for key, value in datasets.items():
        expected_type = allowed[key][1]
        if not isinstance(value, expected_type):
            type_name = "object" if expected_type is dict else "list"
            raise IntakeError(f"Backup dataset {key} must be a JSON {type_name}.")
        validated[key] = value

    return {
        "backup": backup,
        "datasets": validated,
        "counts": backup_counts(validated),
        "dataset_names": list(validated.keys()),
    }


def preview_local_backup_import(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    validation = validate_backup_payload(payload, paths)
    return {
        "status": "ready",
        "message": "Backup import is valid. Preview only; no local files were changed.",
        "counts": validation["counts"],
        "dataset_names": validation["dataset_names"],
        "send_allowed": False,
    }


def _parse_profile_mapping_text(value: Any) -> dict[str, str]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return {
            str(source or "").strip(): str(target or "").strip()
            for source, target in value.items()
            if str(source or "").strip() and str(target or "").strip()
        }
    mappings: dict[str, str] = {}
    for raw_line in str(value).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "->" in line:
            source, target = line.split("->", 1)
        elif "=" in line:
            source, target = line.split("=", 1)
        elif ":" in line:
            source, target = line.split(":", 1)
        else:
            raise IntakeError(f"Profile mapping must use source=target or source -> target: {line}")
        source_key = source.strip()
        target_key = target.strip()
        if not source_key or not target_key:
            raise IntakeError(f"Profile mapping is incomplete: {line}")
        mappings[source_key] = target_key
    return mappings


def _action_for_record(current: Any, incoming: Any) -> str:
    if current is None:
        return "create"
    if stable_json_hash(current) == stable_json_hash(incoming):
        return "unchanged"
    return "update"


def _action_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"create": 0, "update": 0, "unchanged": 0}
    for row in rows:
        action = str(row.get("action") or "")
        if action in summary:
            summary[action] += 1
    return summary


def _profile_import_preview_rows(
    *,
    current_profiles: dict[str, Any],
    incoming_profiles: dict[str, Any],
    mappings: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_key in sorted(incoming_profiles):
        incoming_record = incoming_profiles[source_key]
        if not isinstance(incoming_record, dict):
            raise IntakeError(f"Incoming service profile must be an object: {source_key}")
        target_key = mappings.get(source_key, source_key)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", target_key):
            raise IntakeError(f"Target profile key is invalid: {target_key}")
        current_record = current_profiles.get(target_key)
        action = _action_for_record(current_record, incoming_record)
        changes = diff_json_values(current_record or {}, incoming_record) if action == "update" else []
        rows.append({
            "source_key": source_key,
            "target_key": target_key,
            "mapped": target_key != source_key,
            "action": action,
            "incoming_description": str(incoming_record.get("description") or ""),
            "current_description": str((current_record or {}).get("description") or ""),
            "change_count": len(changes),
            "changes": changes[:20],
            "incoming_hash": stable_json_hash(incoming_record),
            "current_hash": stable_json_hash(current_record) if current_record is not None else "",
        })
    return rows


def _court_email_import_preview_rows(
    *,
    current_court_emails: list[dict[str, Any]],
    incoming_court_emails: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current_by_key = {
        str(record.get("key") or "").strip(): record
        for record in current_court_emails
        if str(record.get("key") or "").strip()
    }
    for incoming_raw in incoming_court_emails:
        if not isinstance(incoming_raw, dict):
            raise IntakeError("Incoming court email records must be objects.")
        source_key = str(incoming_raw.get("key") or "").strip()
        current_record = current_by_key.get(source_key)
        incoming_record = normalize_court_email_record(incoming_raw, current_record)
        action = _action_for_record(current_record, incoming_record)
        changes = diff_json_values(current_record or {}, incoming_record) if action == "update" else []
        rows.append({
            "key": incoming_record["key"],
            "action": action,
            "name": incoming_record.get("name", ""),
            "incoming_email": incoming_record.get("email", ""),
            "current_email": str((current_record or {}).get("email") or ""),
            "incoming_aliases": incoming_record.get("payment_entity_aliases", []),
            "current_aliases": (current_record or {}).get("payment_entity_aliases", []),
            "change_count": len(changes),
            "changes": changes[:20],
            "incoming_hash": stable_json_hash(incoming_record),
            "current_hash": stable_json_hash(current_record) if current_record is not None else "",
        })
    return rows


def preview_legalpdf_import(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    validation = validate_backup_payload(payload, paths)
    datasets = validation["datasets"]
    profile_mappings = _parse_profile_mapping_text(
        payload.get("profile_mappings", payload.get("profile_mapping_text", payload.get("profile_mappings_text")))
    )
    current_profiles = load_profiles(paths.service_profiles)
    current_court_emails = read_json_list(paths.court_emails)
    incoming_profiles = datasets.get("service_profiles", {})
    incoming_court_emails = datasets.get("court_emails", [])
    if not isinstance(incoming_profiles, dict):
        raise IntakeError("Incoming service_profiles dataset must be a JSON object.")
    if not isinstance(incoming_court_emails, list):
        raise IntakeError("Incoming court_emails dataset must be a JSON list.")

    profile_rows = _profile_import_preview_rows(
        current_profiles=current_profiles,
        incoming_profiles=incoming_profiles,
        mappings=profile_mappings,
    )
    court_rows = _court_email_import_preview_rows(
        current_court_emails=current_court_emails,
        incoming_court_emails=incoming_court_emails,
    )
    return {
        "status": "previewed",
        "message": "LegalPDF integration import preview is ready. No local files were changed.",
        "counts": validation["counts"],
        "dataset_names": validation["dataset_names"],
        "profile_mappings": profile_rows,
        "profile_action_summary": _action_summary(profile_rows),
        "court_email_differences": court_rows,
        "court_email_action_summary": _action_summary(court_rows),
        "mapping_count": len(profile_mappings),
        "write_allowed": False,
        "send_allowed": False,
    }


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        text = str(value if value is not None else "").replace("\n", " ").strip()
        return text.replace("|", "\\|")

    lines = [
        "| " + " | ".join(cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell(value) for value in row) + " |")
    return "\n".join(lines)


def legalpdf_import_report_markdown(preview: dict[str, Any]) -> str:
    profile_rows = preview.get("profile_mappings") or []
    court_rows = preview.get("court_email_differences") or []
    lines = [
        "# LegalPDF Integration Preview Report",
        "",
        preview.get("message") or "Preview report.",
        "",
        "No local reference files were changed. This report is private runtime output.",
        "",
        "## Dataset Counts",
        "",
        _markdown_table(
            ["Dataset", "Records"],
            [[key, value] for key, value in sorted((preview.get("counts") or {}).items())],
        ),
        "",
        "## Profile Mappings",
        "",
        _markdown_table(
            ["Mapping", "Source", "Target", "Action", "Incoming description", "Changes"],
            [
                [
                    f"{row.get('source_key', '')} -> {row.get('target_key', '')}",
                    row.get("source_key", ""),
                    row.get("target_key", ""),
                    row.get("action", ""),
                    row.get("incoming_description", ""),
                    row.get("change_count", 0),
                ]
                for row in profile_rows
            ],
        ),
        "",
        "## Court Email Differences",
        "",
        _markdown_table(
            ["Key", "Action", "Incoming email", "Current email", "Name", "Changes"],
            [
                [
                    row.get("key", ""),
                    row.get("action", ""),
                    row.get("incoming_email", ""),
                    row.get("current_email", ""),
                    row.get("name", ""),
                    row.get("change_count", 0),
                ]
                for row in court_rows
            ],
        ),
        "",
        "## Safety",
        "",
        "- `write_allowed`: false",
        "- `send_allowed`: false",
        "- Reference files, duplicate indexes, Gmail draft logs, and Gmail itself are untouched.",
        "",
    ]
    return "\n".join(lines)


def _profile_checklist_task(row: dict[str, Any]) -> dict[str, Any]:
    source_key = str(row.get("source_key") or "").strip()
    target_key = str(row.get("target_key") or source_key).strip()
    action = str(row.get("action") or "").strip()
    mapping = f"{source_key} -> {target_key}" if source_key and target_key and source_key != target_key else target_key or source_key
    change_count = int(row.get("change_count") or 0)
    if action == "create":
        task_action = "create"
        title = f"Create service profile {target_key}."
        detail = f"Review the incoming LegalPDF profile {source_key} and add a sanitized honorários profile only when it matches this project's PDF-only rules."
    elif action == "update":
        task_action = "review_update"
        title = f"Review service profile mapping {mapping}."
        detail = f"Reconcile {change_count} proposed profile change{'' if change_count == 1 else 's'} before any future adapter import."
    elif action == "unchanged":
        task_action = "verify_unchanged"
        title = f"Verify unchanged service profile {mapping}."
        detail = "No data change is proposed; keep this as evidence that the LegalPDF and honorários profile already align."
    else:
        task_action = "review"
        title = f"Review service profile {mapping}."
        detail = "Unknown preview action; review this row manually before any future integration work."
    return {
        "category": "service_profile",
        "action": task_action,
        "title": title,
        "detail": detail,
        "source_key": source_key,
        "target_key": target_key,
        "change_count": change_count,
        "blocking": False,
    }


def _court_email_checklist_task(row: dict[str, Any]) -> dict[str, Any]:
    key = str(row.get("key") or "").strip()
    action = str(row.get("action") or "").strip()
    incoming_email = str(row.get("incoming_email") or "").strip()
    current_email = str(row.get("current_email") or "").strip()
    change_count = int(row.get("change_count") or 0)
    if action == "create":
        task_action = "create"
        title = f"Add court email alias {key}."
        detail = f"Review and add {incoming_email} only if it is the correct payment-entity recipient for this workflow."
    elif action == "update":
        task_action = "review_update"
        title = f"Review court email {key}."
        detail = f"Compare current {current_email or 'blank'} with incoming {incoming_email or 'blank'} across {change_count} proposed change{'' if change_count == 1 else 's'}."
    elif action == "unchanged":
        task_action = "verify_unchanged"
        title = f"Verify unchanged court email {key}."
        detail = "No court-email change is proposed; keep this as evidence for a later LegalPDF adapter."
    else:
        task_action = "review"
        title = f"Review court email {key}."
        detail = "Unknown preview action; review this row manually before any future integration work."
    return {
        "category": "court_email",
        "action": task_action,
        "title": title,
        "detail": detail,
        "source_key": key,
        "target_key": key,
        "incoming_email": incoming_email,
        "current_email": current_email,
        "change_count": change_count,
        "blocking": False,
    }


PROFILE_DEFAULT_REMOVAL_BLOCK_PREFIXES = (
    "defaults.addressee",
    "defaults.payment_entity",
    "defaults.recipient_email",
    "defaults.court_email_key",
    "defaults.service_entity",
    "defaults.service_entity_type",
    "defaults.entities_differ",
    "defaults.service_place",
    "defaults.service_place_phrase",
    "defaults.transport",
    "defaults.closing_city",
)


def _change_path_is_required_profile_default(path: str) -> bool:
    path = str(path or "").strip()
    return any(path == prefix or path.startswith(f"{prefix}.") for prefix in PROFILE_DEFAULT_REMOVAL_BLOCK_PREFIXES)


def _removed_required_profile_default_paths(row: dict[str, Any]) -> list[str]:
    def removed_leaf_paths(path: str, value: Any) -> list[str]:
        if isinstance(value, dict):
            leaves: list[str] = []
            for key, child in value.items():
                leaves.extend(removed_leaf_paths(f"{path}.{key}", child))
            return leaves or [path]
        return [path]

    paths: list[str] = []
    for change in row.get("changes") or []:
        if not isinstance(change, dict):
            continue
        path = str(change.get("path") or "")
        if change.get("change") == "removed" and _change_path_is_required_profile_default(path):
            paths.extend(removed_leaf_paths(path, change.get("before")))
    return sorted(dict.fromkeys(paths))


def _is_test_email(email: str) -> bool:
    value = str(email or "").strip().casefold()
    if not value or "@" not in value:
        return False
    domain = value.rsplit("@", 1)[-1]
    return domain.endswith(".test") or domain in {"example.com", "example.org", "example.net"}


def _profile_import_plan_task(row: dict[str, Any]) -> dict[str, Any]:
    task = _profile_checklist_task(row)
    action = str(row.get("action") or "").strip()
    blocked_paths = _removed_required_profile_default_paths(row) if action == "update" else []
    blockers: list[str] = []
    if blocked_paths:
        blockers.append("incoming update would remove local Honorários defaults")
    if action == "update":
        merge_policy = "preserve_local_required_fields"
    elif action == "create":
        merge_policy = "create_sanitized_profile_after_review"
    else:
        merge_policy = "no_data_change"
    task.update({
        "blocking": bool(blockers),
        "blockers": blockers,
        "blocked_paths": blocked_paths,
        "merge_policy": merge_policy,
        "apply_allowed": False,
    })
    return task


def _court_email_import_plan_task(row: dict[str, Any]) -> dict[str, Any]:
    task = _court_email_checklist_task(row)
    action = str(row.get("action") or "").strip()
    incoming_email = str(row.get("incoming_email") or "").strip()
    current_email = str(row.get("current_email") or "").strip()
    incoming_is_test_email = _is_test_email(incoming_email)
    would_change_existing_real_email = (
        action == "update"
        and bool(current_email)
        and bool(incoming_email)
        and current_email.casefold() != incoming_email.casefold()
        and not _is_test_email(current_email)
    )
    blockers: list[str] = []
    if incoming_is_test_email:
        blockers.append("incoming court email is a test/synthetic address")
    if would_change_existing_real_email:
        blockers.append("incoming court email would change an existing real recipient")
    if action == "update":
        merge_policy = "preserve_existing_recipient_unless_verified"
    elif action == "create":
        merge_policy = "add_alias_after_recipient_review"
    else:
        merge_policy = "no_data_change"
    task.update({
        "blocking": bool(blockers),
        "blockers": blockers,
        "requires_recipient_review": action in {"create", "update"} or bool(blockers),
        "incoming_is_test_email": incoming_is_test_email,
        "would_change_existing_real_email": would_change_existing_real_email,
        "merge_policy": merge_policy,
        "apply_allowed": False,
    })
    return task


def legalpdf_integration_checklist_markdown(checklist: list[dict[str, Any]], preview: dict[str, Any]) -> str:
    rows = [
        [
            task.get("number", ""),
            task.get("category", ""),
            task.get("action", ""),
            f"{task.get('source_key', '')} -> {task.get('target_key', '')}" if task.get("source_key") != task.get("target_key") else task.get("target_key", ""),
            task.get("title", ""),
        ]
        for task in checklist
    ]
    lines = [
        "# LegalPDF Integration Checklist",
        "",
        "Concrete future-adapter tasks derived from the read-only LegalPDF integration preview.",
        "",
        "No local reference files were changed. Gmail draft behavior is not involved.",
        "",
        "## Preview Summary",
        "",
        f"- Profiles: {json.dumps(preview.get('profile_action_summary') or {}, ensure_ascii=False, sort_keys=True)}",
        f"- Court emails: {json.dumps(preview.get('court_email_action_summary') or {}, ensure_ascii=False, sort_keys=True)}",
        "",
        "## Tasks",
        "",
        _markdown_table(["#", "Category", "Action", "Key", "Task"], rows),
        "",
        "## Safety",
        "",
        "- `write_allowed`: false",
        "- `send_allowed`: false",
        "- `managed_data_changed`: false",
        "",
    ]
    return "\n".join(lines)


def legalpdf_adapter_import_plan_markdown(plan: dict[str, Any]) -> str:
    tasks = plan.get("tasks") or []
    rows = [
        [
            task.get("number", ""),
            task.get("category", ""),
            task.get("action", ""),
            "yes" if task.get("blocking") else "no",
            task.get("merge_policy", ""),
            "; ".join(task.get("blockers") or []),
        ]
        for task in tasks
    ]
    lines = [
        "# LegalPDF Adapter Import Plan",
        "",
        "Read-only future-adapter plan derived from the LegalPDF integration checklist.",
        "",
        "No local reference files were changed. No LegalPDF files were touched. Gmail draft behavior is not involved.",
        "",
        "## Safety",
        "",
        "- `write_allowed`: false",
        "- `send_allowed`: false",
        "- `managed_data_changed`: false",
        "- `apply_endpoint_available`: false",
        f"- Blocking tasks: {plan.get('blocking_count', 0)}",
        "",
        "## Tasks",
        "",
        _markdown_table(["#", "Category", "Action", "Blocking", "Merge policy", "Blockers"], rows),
        "",
    ]
    return "\n".join(lines)


def build_legalpdf_integration_checklist(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    preview = preview_legalpdf_import(payload, paths)
    tasks: list[dict[str, Any]] = []
    for row in preview.get("profile_mappings") or []:
        if isinstance(row, dict):
            tasks.append(_profile_checklist_task(row))
    for row in preview.get("court_email_differences") or []:
        if isinstance(row, dict):
            tasks.append(_court_email_checklist_task(row))
    for index, task in enumerate(tasks, start=1):
        task["number"] = index
    return {
        "status": "checklist_ready",
        "message": "LegalPDF integration checklist is ready. No local files were changed.",
        "checklist": tasks,
        "checklist_markdown": legalpdf_integration_checklist_markdown(tasks, preview),
        "preview": preview,
        "write_allowed": False,
        "send_allowed": False,
        "managed_data_changed": False,
    }


def build_legalpdf_adapter_import_plan(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    preview = preview_legalpdf_import(payload, paths)
    tasks: list[dict[str, Any]] = []
    for row in preview.get("profile_mappings") or []:
        if isinstance(row, dict):
            tasks.append(_profile_import_plan_task(row))
    for row in preview.get("court_email_differences") or []:
        if isinstance(row, dict):
            tasks.append(_court_email_import_plan_task(row))
    for index, task in enumerate(tasks, start=1):
        task["number"] = index
    blocking_count = sum(1 for task in tasks if task.get("blocking"))
    plan = {
        "status": "plan_ready",
        "message": "LegalPDF adapter import plan is ready. No local files were changed and no apply endpoint exists.",
        "tasks": tasks,
        "blocking_count": blocking_count,
        "preview": preview,
        "write_allowed": False,
        "send_allowed": False,
        "managed_data_changed": False,
        "apply_endpoint_available": False,
    }
    plan["plan_markdown"] = legalpdf_adapter_import_plan_markdown(plan)
    return plan


def export_legalpdf_import_report(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    preview = preview_legalpdf_import(payload, paths)
    report_id = f"legalpdf-import-preview-{timestamp_slug()}-{secrets.token_hex(4)}"
    paths.integration_report_output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = paths.integration_report_output_dir / f"{report_id}.md"
    json_path = paths.integration_report_output_dir / f"{report_id}.json"
    report = {
        "kind": "legalpdf_integration_preview_report",
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "preview": preview,
        "managed_data_changed": False,
        "reference_write_allowed": False,
        "send_allowed": False,
    }
    markdown_path.write_text(legalpdf_import_report_markdown(preview), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "report_exported",
        "message": "LegalPDF integration preview report exported. No local reference files were changed.",
        "preview": preview,
        "preview_report_markdown_file": str(markdown_path),
        "preview_report_json_file": str(json_path),
        "managed_data_changed": False,
        "reference_write_allowed": False,
        "send_allowed": False,
    }


def restore_local_backup(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    if not bool(payload.get("confirm_restore")):
        raise IntakeError("Backup restore requires confirm_restore=true.")
    validation = validate_backup_payload(payload, paths)
    pre_restore_backup = backup_payload(paths)
    pre_restore_backup["reason"] = "Automatic backup before local restore."
    pre_restore_file = write_backup_file(pre_restore_backup, paths, prefix="pre-restore-backup")

    dataset_paths = backup_dataset_paths(paths)
    for key, data in validation["datasets"].items():
        target_path, expected_type = dataset_paths[key]
        if expected_type is dict:
            write_json_object(target_path, data)
        else:
            write_json_list(target_path, data)

    return {
        "status": "restored",
        "message": "Backup restored locally. A pre-restore backup was written first.",
        "restored_datasets": validation["dataset_names"],
        "counts": validation["counts"],
        "pre_restore_backup_file": str(pre_restore_file),
        "backup_status": backup_status_payload(paths),
        "send_allowed": False,
    }


def stable_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def diff_json_values(before: Any, after: Any, prefix: str = "") -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before:
                changes.append({"path": path, "change": "added", "before": None, "after": after[key]})
            elif key not in after:
                changes.append({"path": path, "change": "removed", "before": before[key], "after": None})
            else:
                changes.extend(diff_json_values(before[key], after[key], path))
        return changes
    if before != after:
        return [{"path": prefix, "change": "updated", "before": before, "after": after}]
    return []


def profile_change_payload(
    *,
    profile_key: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    reason: str = "",
) -> dict[str, Any]:
    changed_at = datetime.now(timezone.utc).isoformat()
    changes = diff_json_values(before or {}, after)
    action = "created" if before is None else "updated" if changes else "unchanged"
    after_hash = stable_json_hash(after)
    return {
        "change_id": f"{timestamp_slug()}_{after_hash[:12]}",
        "changed_at": changed_at,
        "profile_key": profile_key,
        "action": action,
        "reason": str(reason or "").strip(),
        "before_hash": stable_json_hash(before) if before is not None else "",
        "after_hash": after_hash,
        "before_profile": copy.deepcopy(before) if before is not None else None,
        "after_profile": copy.deepcopy(after),
        "changes": changes,
        "send_allowed": False,
    }


def append_profile_change_log(change: dict[str, Any], paths: AppPaths) -> None:
    records = read_json_list(paths.profile_change_log)
    records.append(change)
    write_json_list(paths.profile_change_log, records)


def _coerce_reference_bool(value: Any, *, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "sim", "on"}:
        return True
    if text in {"0", "false", "no", "não", "nao", "off"}:
        return False
    raise IntakeError(f"Boolean value expected, got: {value}")


def normalize_service_profile_record(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    key = str(payload.get("key") or payload.get("profile") or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
        raise IntakeError("key is required and must use lowercase letters, numbers, and underscores.")
    existing = existing or {}
    description = str(payload.get("description", existing.get("description", "")) or "").strip()
    if not description:
        raise IntakeError("description is required.")

    defaults = copy.deepcopy(existing.get("defaults") or {})
    simple_fields = [
        "service_date_source",
        "addressee",
        "payment_entity",
        "service_entity",
        "service_entity_type",
        "service_place",
        "service_place_phrase",
        "closing_city",
        "recipient_email",
        "court_email_key",
        "recipient_override_reason",
    ]
    for field in simple_fields:
        if field in payload:
            value = payload.get(field)
            if value in (None, ""):
                defaults.pop(field, None)
            else:
                defaults[field] = str(value).strip()

    if defaults.get("recipient_email"):
        defaults["recipient_email"] = str(defaults["recipient_email"]).strip().lower()
        if not _looks_like_email(defaults["recipient_email"]):
            raise IntakeError("recipient_email must be a valid email address.")

    source = str(defaults.get("service_date_source") or "").strip()
    if source and source not in ALLOWED_SERVICE_DATE_SOURCES:
        allowed = ", ".join(sorted(ALLOWED_SERVICE_DATE_SOURCES))
        raise IntakeError(f"service_date_source must be one of: {allowed}")

    entity_type = str(defaults.get("service_entity_type") or "").strip()
    if entity_type and entity_type not in ALLOWED_SERVICE_ENTITY_TYPES:
        allowed = ", ".join(sorted(ALLOWED_SERVICE_ENTITY_TYPES))
        raise IntakeError(f"service_entity_type must be one of: {allowed}")

    if "entities_differ" in payload:
        defaults["entities_differ"] = _coerce_reference_bool(payload.get("entities_differ"), default=bool(defaults.get("entities_differ")))
    if "claim_transport" in payload:
        defaults["claim_transport"] = _coerce_reference_bool(payload.get("claim_transport"), default=bool(defaults.get("claim_transport")))

    transport = copy.deepcopy(defaults.get("transport") or {})
    if "transport_origin" in payload and payload.get("transport_origin") not in (None, ""):
        transport["origin"] = str(payload.get("transport_origin")).strip()
    if "transport_destination" in payload and payload.get("transport_destination") not in (None, ""):
        transport["destination"] = str(payload.get("transport_destination")).strip()
    if "km_one_way" in payload and payload.get("km_one_way") not in (None, ""):
        transport["km_one_way"] = _coerce_positive_int(payload.get("km_one_way"), field="km_one_way")
    if transport:
        transport.setdefault("origin", "Marmelar")
        transport.setdefault("round_trip_phrase", "ida_volta")
        defaults["transport"] = transport

    defaults.setdefault("source_filename", "user-provided-service-details")

    record = {
        "description": description,
        "defaults": defaults,
        "source_text_template": str(payload.get("source_text_template", existing.get("source_text_template", "")) or "").strip(),
        "notes_template": str(payload.get("notes_template", existing.get("notes_template", "")) or "").strip(),
    }
    return key, record


def preview_service_profile(profile_key: str, record: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    profiles = {profile_key: record}
    sample_intake = build_intake(
        profile_name=profile_key,
        case_number="999/26.0TEST",
        service_date="2026-05-03",
        profiles=profiles,
        today="2026-05-03",
    )
    questions = missing_questions(sample_intake)
    preview: dict[str, Any] = {
        "status": "needs_info" if questions else "ready",
        "sample_intake": sample_intake,
        "questions": question_payload(questions),
        "send_allowed": False,
    }
    if questions:
        preview["question_text"] = format_numbered_questions(questions)
        return preview

    profile = load_json(paths.profile)
    email_config = load_json(paths.email_config)
    court_directory = read_json_list(paths.court_emails)
    rendered = build_rendered_request(sample_intake, profile)
    recipient, recipient_source = resolve_recipient(sample_intake, email_config, court_directory)
    preview.update({
        "case_number": rendered.case_number,
        "service_date": sample_intake.get("service_date", ""),
        "recipient": recipient,
        "recipient_source": recipient_source,
        "draft_text": rendered_request_text(rendered),
    })
    return preview


def preview_service_profile_upsert(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IntakeError("Service profile payload must be an object.")
    profiles = load_profiles(paths.service_profiles)
    key_value = str(payload.get("key") or payload.get("profile") or "").strip()
    existing = profiles.get(key_value)
    if existing is not None and not isinstance(existing, dict):
        raise IntakeError(f"Existing profile is invalid: {key_value}")
    key, record = normalize_service_profile_record(payload, existing)
    preview = preview_service_profile(key, record, paths)
    change = profile_change_payload(
        profile_key=key,
        before=copy.deepcopy(existing) if existing is not None else None,
        after=record,
        reason=str(payload.get("change_reason") or ""),
    )
    return {
        "status": "preview",
        "kind": "service_profile",
        "key": key,
        "record": record,
        "preview": preview,
        "profile_change": change,
        "send_allowed": False,
    }


def upsert_service_profile(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    result = preview_service_profile_upsert(payload, paths)
    key = result["key"]
    record = result["record"]
    change = result["profile_change"]
    profiles = load_profiles(paths.service_profiles)
    updated_profiles = copy.deepcopy(profiles)
    updated_profiles[key] = record
    write_json_object(paths.service_profiles, updated_profiles)
    if change.get("changes"):
        append_profile_change_log(change, paths)
    return {
        "status": "saved",
        "kind": "service_profile",
        "key": key,
        "record": record,
        "preview": result["preview"],
        "profile_change": change,
        "count": len(updated_profiles),
        "send_allowed": False,
    }


def _find_profile_change(payload: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    change_id = str(payload.get("change_id") or "").strip()
    if change_id:
        for record in records:
            if str(record.get("change_id") or "").strip() == change_id:
                return record
        raise IntakeError(f"Unknown profile change ID: {change_id}")
    if payload.get("change_index") not in (None, ""):
        try:
            index = int(str(payload.get("change_index")).strip())
        except ValueError as exc:
            raise IntakeError("change_index must be a number.") from exc
        if index < 0 or index >= len(records):
            raise IntakeError(f"Profile change index is out of range: {index}")
        return records[index]
    raise IntakeError("Missing change_id or change_index for profile rollback.")


def preview_profile_rollback(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    records = read_json_list(paths.profile_change_log)
    record = _find_profile_change(payload, records)
    profile_key = str(record.get("profile_key") or "").strip()
    if not profile_key:
        raise IntakeError("Profile change log entry is missing profile_key.")
    if "before_profile" not in record or "after_profile" not in record:
        raise IntakeError("This profile change log entry cannot be rolled back because it has no profile snapshots.")

    profiles = load_profiles(paths.service_profiles)
    current_profile = profiles.get(profile_key)
    after_profile = record.get("after_profile")
    if current_profile is None:
        raise IntakeError(f"Current profile does not exist: {profile_key}")
    if stable_json_hash(current_profile) != stable_json_hash(after_profile):
        raise IntakeError(
            "This profile has changed since this log entry. Refresh the profile history and roll back the latest matching change first."
        )

    target_profile = record.get("before_profile")
    reason = str(payload.get("reason") or payload.get("change_reason") or "").strip()
    rollback_change = profile_change_payload(
        profile_key=profile_key,
        before=current_profile,
        after=target_profile or {},
        reason=reason,
    )
    rollback_change["action"] = "rolled_back"
    rollback_change["rollback_of"] = str(record.get("change_id") or "")

    if target_profile is None:
        preview = {
            "status": "will_remove",
            "message": f"Rollback will remove profile {profile_key}.",
            "questions": [],
            "send_allowed": False,
        }
    else:
        preview = preview_service_profile(profile_key, target_profile, paths)
    return {
        "status": "preview",
        "kind": "service_profile_rollback",
        "key": profile_key,
        "rollback_target": target_profile,
        "preview": preview,
        "profile_change": rollback_change,
        "send_allowed": False,
    }


def rollback_service_profile(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    preview_result = preview_profile_rollback(payload, paths)
    profile_key = preview_result["key"]
    target_profile = preview_result.get("rollback_target")
    profiles = load_profiles(paths.service_profiles)
    updated_profiles = copy.deepcopy(profiles)
    if target_profile is None:
        updated_profiles.pop(profile_key, None)
    else:
        updated_profiles[profile_key] = target_profile
    write_json_object(paths.service_profiles, updated_profiles)
    append_profile_change_log(preview_result["profile_change"], paths)
    return {
        **preview_result,
        "status": "rolled_back",
        "count": len(updated_profiles),
        "send_allowed": False,
    }


def rendered_request_text(rendered: RenderedRequest) -> str:
    lines = [
        f"Número de processo: {rendered.case_number}",
        "",
        rendered.addressee,
        "",
        f"Nome: {rendered.applicant_name}",
        f"Morada: {rendered.address}",
        "",
        rendered.service_paragraph,
        "",
    ]
    if rendered.transport_paragraph:
        lines.extend([rendered.transport_paragraph, ""])
    lines.extend([
        rendered.vat_irs_phrase,
        "",
        f"{rendered.payment_phrase} {rendered.iban}",
        "",
        rendered.closing_phrase,
        "",
        f"{rendered.closing_city}, {rendered.closing_date_long}",
        "",
        rendered.signature_label,
        "",
        rendered.signature_name,
    ])
    return "\n".join(lines)


def question_payload(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "number": question["number"],
            "field": question["field"],
            "question": question["question"],
            "answer_hint": question["answer_hint"],
        }
        for question in questions
    ]


def set_nested_value(data: dict[str, Any], field_path: str, value: Any) -> None:
    target = data
    parts = field_path.split(".")
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            child = {}
            target[part] = child
        target = child
    target[parts[-1]] = value


def coerce_answer_bool(value: str) -> bool:
    text = fold_match_text(value)
    if text in {"yes", "y", "sim", "true", "1", "on"}:
        return True
    if text in {"no", "n", "nao", "não", "false", "0", "off"}:
        return False
    raise IntakeError(f"Expected yes/no answer, got: {value}")


def coerce_answer_int(value: str) -> int | str:
    digits = re.sub(r"[^\d]", "", str(value or ""))
    if digits:
        return int(digits)
    return str(value or "").strip()


def answer_to_iso_date(value: str) -> str:
    text = str(value or "").strip()
    if _looks_like_iso_date(text):
        return text
    extracted = extract_first_date(text)
    return extracted


def apply_answer_to_intake(intake: dict[str, Any], field: str, answer: str) -> None:
    value = str(answer or "").strip()
    if not value:
        return

    if field == "service_date_source":
        folded = fold_match_text(value)
        if folded in {"metadata", "photo", "foto", "image", "imagem"}:
            metadata_date = str(intake.get("photo_metadata_date") or "").strip()
            if not metadata_date:
                raise IntakeError("Cannot use metadata date because photo_metadata_date is missing.")
            intake["service_date"] = metadata_date
            intake["service_date_source"] = "photo_metadata_user_confirmed"
            return
        if folded in {"document", "documento", "paper", "source", "texto"}:
            intake["service_date_source"] = "document_text_user_confirmed"
            return
        explicit_date = answer_to_iso_date(value)
        if explicit_date:
            intake["service_date"] = explicit_date
            intake["service_date_source"] = "user_confirmed_exception"
            return
        intake["service_date_source"] = value
        return

    if field == "service_date":
        explicit_date = answer_to_iso_date(value)
        if not explicit_date:
            raise IntakeError("Service date answer must include a valid date.")
        intake["service_date"] = explicit_date
        intake["service_date_source"] = "user_confirmed"
        return

    if field == "claim_transport":
        claim = coerce_answer_bool(value)
        intake["claim_transport"] = claim
        if not claim:
            intake.pop("transport", None)
        return

    if field == "transport.km_one_way":
        set_nested_value(intake, field, coerce_answer_int(value))
        return

    if field == "payment_entity":
        intake["payment_entity"] = value
        if not str(intake.get("addressee") or "").strip():
            intake["addressee"] = _default_addressee(value)
        return

    if field == "service_place":
        intake["service_place"] = value
        if not str(intake.get("service_place_phrase") or "").strip():
            source_context = combine_text_parts(str(intake.get("source_text") or ""), str(intake.get("service_entity") or ""))
            if "policia judiciaria" in fold_match_text(source_context):
                intake["service_place_phrase"] = f"em diligência da Polícia Judiciária realizada em {value}"
            else:
                intake["service_place_phrase"] = f"em diligência realizada em {value}"
        return

    if field == "service_entity":
        intake["service_entity"] = value
        if not str(intake.get("service_place") or "").strip():
            intake["service_place"] = value
        folded = fold_match_text(value)
        if "gnr" in folded or "guarda nacional republicana" in folded:
            intake["service_entity_type"] = "gnr"
            intake["entities_differ"] = True
        elif "psp" in folded or "policia de seguranca publica" in folded:
            intake["service_entity_type"] = "psp"
            intake["entities_differ"] = True
        return

    set_nested_value(intake, field, value)


def apply_numbered_answers(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IntakeError("Request must be a JSON object.")
    intake = copy.deepcopy(payload.get("intake") or {})
    if not isinstance(intake, dict):
        raise IntakeError("Request must include an intake object.")
    answer_text = str(payload.get("answers") or payload.get("answer_text") or "").strip()
    if not answer_text:
        raise IntakeError("Paste numbered answers before applying them.")

    questions = missing_questions(intake)
    mapped = parse_numbered_answers(answer_text, questions)
    applied_fields: list[str] = []
    for question in questions:
        field = str(question.get("field") or "")
        if field not in mapped:
            continue
        apply_answer_to_intake(intake, field, mapped[field])
        applied_fields.append(field)

    review = review_intake(intake, paths)
    return {
        **review,
        "intake": intake,
        "applied_fields": applied_fields,
        "mapped_answers": mapped,
        "send_allowed": False,
    }


def duplicate_payload(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    keys = [
        "case_number",
        "service_date",
        "service_period_label",
        "status",
        "draft_id",
        "message_id",
        "thread_id",
        "recipient",
        "recipient_email",
        "pdf",
        "source_filename",
        "sent_date",
    ]
    payload = {key: record.get(key, "") for key in keys if record.get(key, "")}
    payload.setdefault("status", duplicate_record_status(record))
    return payload


def draft_payload(record: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "case_number",
        "service_date",
        "service_period_label",
        "service_start_time",
        "service_end_time",
        "status",
        "draft_id",
        "message_id",
        "thread_id",
        "recipient",
        "pdf",
        "draft_payload",
        "superseded_by",
        "supersedes",
        "notes",
        "updated_at",
    ]
    return {key: copy.deepcopy(record.get(key, "")) for key in keys if record.get(key, "") not in (None, "")}


def _identity_matches(intake: dict[str, Any], record: dict[str, Any]) -> bool:
    try:
        intake_service_date = get_service_date_value(intake)
    except IntakeError:
        return False
    intake_key = request_identity_key({
        "case_number": str(intake.get("case_number") or ""),
        "service_date": intake_service_date,
        "service_period_label": str(intake.get("service_period_label") or ""),
    })
    record_key = request_identity_key(record)
    if record_key[0] != intake_key[0] or record_key[1] != intake_key[1]:
        return False
    if intake_key[2] or record_key[2]:
        if intake_key[2] and record_key[2] and intake_key[2] != record_key[2]:
            return False
    return True


def matching_duplicate_records(intake: dict[str, Any], paths: AppPaths) -> list[dict[str, Any]]:
    return [
        record
        for record in read_json_list(paths.duplicate_index)
        if duplicate_record_blocks(record) and _identity_matches(intake, record)
    ]


def draft_lifecycle_for_intake(intake: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    duplicate_records = matching_duplicate_records(intake, paths)
    draft_log = load_draft_log(paths.draft_log)
    active_drafts = [draft_payload(record) for record in active_drafts_for(intake, draft_log)]
    duplicate_records_payload = [duplicate_payload(record) for record in duplicate_records]
    has_sent_duplicate = any(duplicate_record_status(record) == "sent" for record in duplicate_records)
    has_drafted_duplicate = any(duplicate_record_status(record) == "drafted" for record in duplicate_records)
    replacement_allowed = (bool(active_drafts) or has_drafted_duplicate) and not has_sent_duplicate
    status = "blocked" if duplicate_records or active_drafts else "clear"
    message = "No active Gmail draft or duplicate blocker found."
    if replacement_allowed:
        message = "Active/drafted request found. Correction mode can prepare a replacement draft after a reason is provided."
    elif has_sent_duplicate:
        message = "A sent request already exists for this case/date. Correction mode is not available."
    elif duplicate_records or active_drafts:
        message = "A blocking draft lifecycle record exists for this request."
    return {
        "status": status,
        "message": message,
        "active_gmail_drafts": active_drafts,
        "duplicate": duplicate_records_payload[0] if duplicate_records_payload else None,
        "duplicate_records": duplicate_records_payload,
        "replacement_allowed": replacement_allowed,
        "blocking_statuses": sorted(BLOCKING_DUPLICATE_STATUSES),
        "send_allowed": False,
    }


def next_safe_action(
    *,
    state: str,
    title: str,
    detail: str,
    button_id: str = "",
    blocked: bool = False,
) -> dict[str, Any]:
    return {
        "state": state,
        "title": title,
        "detail": detail,
        "button_id": button_id,
        "blocked": bool(blocked),
        "send_allowed": False,
    }


def review_next_safe_action(status: str, *, questions: list[dict[str, Any]] | None = None, duplicate: dict[str, Any] | None = None) -> dict[str, Any]:
    if status == "set_aside":
        return next_safe_action(
            state="set_aside_translation",
            title="Set this source aside",
            detail="This looks like a translation or word-count request. Do not generate an interpreting honorários PDF from it.",
            blocked=True,
        )
    if status == "needs_info":
        count = len(questions or [])
        return next_safe_action(
            state="answer_questions",
            title="Answer the numbered questions",
            detail=f"Provide the missing value{'s' if count != 1 else ''} using short numbered replies, then apply the answers and review again.",
            button_id="apply-numbered-answers",
            blocked=True,
        )
    if status == "duplicate":
        duplicate_status = duplicate_record_status(duplicate or {})
        if duplicate_status == "drafted":
            return next_safe_action(
                state="choose_correction_mode",
                title="Review the existing draft first",
                detail="A drafted request already protects this case/date. Only prepare a replacement if this is an intentional correction and you add a correction reason.",
                button_id="prepare-replacement-draft",
                blocked=True,
            )
        return next_safe_action(
            state="stop_duplicate_sent",
            title="Stop before generating",
            detail="A sent request already exists for this case/date. Treat this as a likely duplicate unless you confirm a separate service period.",
            blocked=True,
        )
    if status == "active_draft":
        return next_safe_action(
            state="choose_correction_mode",
            title="Use correction mode only if replacing",
            detail="An active Gmail draft already exists. Add a correction reason before preparing any replacement PDF or payload.",
            button_id="prepare-replacement-draft",
            blocked=True,
        )
    if status == "error":
        return next_safe_action(
            state="fix_blocker",
            title="Fix the intake blocker",
            detail="Resolve the validation error shown above, then review the request again before generating anything.",
            button_id="review-intake",
            blocked=True,
        )
    return next_safe_action(
        state="prepare_pdf",
        title="Review the draft text, then prepare",
        detail="Confirm the Portuguese text, recipient, service date, place, and kilometers. Then create the fee-request PDF and draft payload.",
        button_id="drawer-prepare-intake",
        blocked=False,
    )


def prepared_next_safe_action(packet_mode: bool = False) -> dict[str, Any]:
    attachment_label = "packet PDF" if packet_mode else "generated PDF"
    return next_safe_action(
        state="review_gmail_draft_args",
        title="Review Gmail draft args before handoff",
        detail=(
            f"Inspect the {attachment_label}, recipient, body, and attachment array. Then use Gmail _create_draft outside the app and record the returned IDs locally."
        ),
        button_id="record-parsed-prepared-draft",
        blocked=False,
    )


def load_app_reference(paths: AppPaths) -> dict[str, Any]:
    duplicate_records = read_json_list(paths.duplicate_index)
    draft_records = read_json_list(paths.draft_log)
    return {
        "service_profiles": load_profiles(paths.service_profiles),
        "court_emails": read_json_list(paths.court_emails),
        "known_destinations": load_known_destinations(paths),
        "duplicates": duplicate_records,
        "draft_log": draft_records,
        "profile_change_log": read_json_list(paths.profile_change_log),
        "gmail": {
            "tool": "_create_draft",
            "send_allowed": False,
            "draft_only": True,
        },
        "ai": ai_status_payload(paths.ai_config),
        "backup": backup_status_payload(paths),
    }


def build_profile_intake(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    profiles = load_profiles(paths.service_profiles)
    return build_intake(
        profile_name=str(payload.get("profile") or payload.get("profile_name") or ""),
        case_number=str(payload.get("case_number") or ""),
        service_date=str(payload.get("service_date") or ""),
        profiles=profiles,
        closing_date=payload.get("closing_date"),
        service_date_source=payload.get("service_date_source"),
        service_period_label=payload.get("service_period_label"),
        service_start_time=payload.get("service_start_time"),
        service_end_time=payload.get("service_end_time"),
        raw_case_number=payload.get("raw_case_number"),
        source_case_number=payload.get("source_case_number"),
        photo_metadata_date=payload.get("photo_metadata_date"),
        source_document_timestamp=payload.get("source_document_timestamp"),
        addressee=payload.get("addressee"),
        payment_entity=payload.get("payment_entity"),
        service_entity=payload.get("service_entity"),
        service_entity_type=payload.get("service_entity_type"),
        service_place=payload.get("service_place"),
        service_place_phrase=payload.get("service_place_phrase"),
        recipient_email=payload.get("recipient_email"),
        court_email_key=payload.get("court_email_key"),
        transport_destination=payload.get("transport_destination"),
        km_one_way=payload.get("km_one_way"),
        additional_attachment_files=payload.get("additional_attachment_files"),
        email_body=payload.get("email_body"),
        source_filename=payload.get("source_filename"),
        source_text=payload.get("source_text"),
        notes=payload.get("notes"),
    )


def review_intake(intake: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    translation_matches = detect_translation_source(intake)
    if translation_matches:
        return {
            "status": "set_aside",
            "message": format_translation_rejection(translation_matches),
            "questions": [],
            "next_safe_action": review_next_safe_action("set_aside"),
            "send_allowed": False,
        }

    questions = missing_questions(intake)
    if questions:
        return {
            "status": "needs_info",
            "message": "Missing information before PDF generation.",
            "questions": question_payload(questions),
            "question_text": format_numbered_questions(questions),
            "next_safe_action": review_next_safe_action("needs_info", questions=question_payload(questions)),
            "send_allowed": False,
        }

    duplicate = find_duplicate_record(intake, paths.duplicate_index)
    if duplicate:
        return {
            "status": "duplicate",
            "message": format_duplicate_message(duplicate),
            "duplicate": duplicate_payload(duplicate),
            "questions": [],
            "next_safe_action": review_next_safe_action("duplicate", duplicate=duplicate),
            "send_allowed": False,
        }

    draft_log = load_draft_log(paths.draft_log)
    active_drafts = active_drafts_for(intake, draft_log)
    if active_drafts:
        draft_ids = ", ".join(str(record.get("draft_id") or "") for record in active_drafts)
        return {
            "status": "active_draft",
            "message": f"Active Gmail draft already recorded for this case/date. Draft ID(s): {draft_ids}.",
            "active_gmail_drafts": active_drafts,
            "questions": [],
            "next_safe_action": review_next_safe_action("active_draft"),
            "send_allowed": False,
        }

    try:
        profile = load_json(paths.profile)
        email_config = load_json(paths.email_config)
        court_directory = read_json_list(paths.court_emails)
        rendered = build_rendered_request(intake, profile)
        recipient, recipient_source = resolve_recipient(intake, email_config, court_directory)
    except (IntakeError, OSError, json.JSONDecodeError) as exc:
        return {
            "status": "error",
            "message": str(exc),
            "questions": [],
            "next_safe_action": review_next_safe_action("error"),
            "send_allowed": False,
        }

    return {
        "status": "ready",
        "message": "Ready for PDF generation and Gmail draft payload preparation.",
        "case_number": rendered.case_number,
        "service_date": str(intake.get("service_date") or intake.get("photo_metadata_date") or ""),
        "payment_entity": str(intake.get("payment_entity") or ""),
        "service_entity": str(intake.get("service_entity") or intake.get("service_place") or ""),
        "recipient": recipient,
        "recipient_source": recipient_source,
        "draft_text": rendered_request_text(rendered),
        "questions": [],
        "next_safe_action": review_next_safe_action("ready"),
        "send_allowed": False,
    }


def planned_intake_paths(intakes: list[dict[str, Any]], paths: AppPaths) -> list[Path]:
    stamp = timestamp_slug()
    planned: list[Path] = []
    for index, intake in enumerate(intakes, start=1):
        stem = default_output_path(intake).stem
        path = paths.intake_output_dir / f"{stem}_{stamp}_{index}.json"
        planned.append(path)
    return planned


def write_intake_files(intakes: list[dict[str, Any]], intake_paths: list[Path]) -> None:
    for intake, path in zip(intakes, intake_paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(intake, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def underlying_requests_for_packet(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for item in items:
        request = {
            "case_number": item.get("case_number", ""),
            "service_date": item.get("service_date", ""),
        }
        for key in ("service_period_label", "service_start_time", "service_end_time"):
            if item.get(key):
                request[key] = item[key]
        requests.append(request)
    return requests


def default_packet_email_body(items: list[dict[str, Any]], email_config: dict[str, Any]) -> str:
    default_body = str(email_config.get("body") or "")
    signature = "Example Interpreter"
    if "Melhores cumprimentos," in default_body:
        signature = default_body.split("Melhores cumprimentos,", 1)[1].strip() or signature
    count = len(items)
    request_word = "requerimento" if count == 1 else "requerimentos"
    return (
        "Bom dia,\n\n"
        "Venho por este meio, requerer o pagamento dos honorários devidos, "
        "em virtude de ter sido nomeado intérprete.\n\n"
        f"Poderão encontrar em anexo um pacote PDF com {count} {request_word} de honorários "
        "correspondentes aos serviços identificados.\n\n"
        "Melhores cumprimentos,\n\n"
        f"{signature}"
    )


def validate_packet_recipients(intakes: list[dict[str, Any]], email_config: dict[str, Any], court_directory: list[dict[str, Any]]) -> str:
    recipients: list[str] = []
    for intake in intakes:
        recipient, _source = resolve_recipient(intake, email_config, court_directory)
        recipients.append(recipient)
    unique = sorted(set(recipients))
    if len(unique) != 1:
        raise IntakeError(
            "Packet mode requires all queued requests to use the same recipient. "
            f"Found: {', '.join(unique)}"
        )
    return unique[0]


def build_packet_result(
    *,
    intakes: list[dict[str, Any]],
    items: list[dict[str, Any]],
    paths: AppPaths,
    email_config: dict[str, Any],
    court_directory: list[dict[str, Any]],
    render_previews: bool,
    preview_warning: str,
) -> dict[str, Any]:
    packet_sources: list[Path] = []
    for item in items:
        for attachment in item.get("attachment_files") or []:
            path = Path(attachment).resolve()
            if path not in packet_sources:
                packet_sources.append(path)

    packet_pdf = paths.packet_output_dir / f"honorarios_packet_{timestamp_slug()}_{secrets.token_hex(4)}.pdf"
    try:
        page_count = build_packet_pdf(packet_sources, packet_pdf)
    except PacketError as exc:
        raise IntakeError(str(exc)) from exc

    packet_intake = copy.deepcopy(intakes[0])
    packet_intake["service_period_label"] = "packet"
    packet_intake.pop("additional_attachment_files", None)
    packet_intake["underlying_requests"] = underlying_requests_for_packet(items)
    packet_intake["email_body"] = str(packet_intake.get("packet_email_body") or "").strip() or default_packet_email_body(items, email_config)

    payload = build_email_payload(packet_intake, packet_pdf, email_config, court_directory)
    payload_errors = validate_draft_payload(payload)
    if payload_errors:
        raise IntakeError(f"Packet draft payload is not Gmail-ready: {'; '.join(payload_errors)}")

    payload_path = paths.draft_output_dir / f"{packet_pdf.stem}.draft.json"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    png_previews = render_png(packet_pdf, paths.render_dir) if render_previews else []
    return {
        "packet_mode": True,
        "case_number": payload["case_number"],
        "service_date": payload["service_date"],
        "service_period_label": payload["service_period_label"],
        "recipient": payload["to"],
        "subject": payload["subject"],
        "pdf": str(packet_pdf.resolve()),
        "page_count": page_count,
        "attachment_files": payload["attachment_files"],
        "attachment_count": len(payload["attachment_files"]),
        "attachment_sha256": payload.get("attachment_sha256", {}),
        "draft_payload": str(payload_path.resolve()),
        "gmail_tool": "_create_draft",
        "gmail_create_draft_args": payload["gmail_create_draft_args"],
        "underlying_requests": payload.get("underlying_requests", []),
        "png_previews": png_previews,
        "png_preview_path": png_previews[0] if png_previews else "",
        "png_preview_urls": [
            artifact_url_for_path(preview, paths)
            for preview in png_previews
            if artifact_url_for_path(preview, paths)
        ],
        "preview_warning": preview_warning,
        "draft_only": True,
        "send_allowed": False,
        "gmail_create_draft_ready": bool(payload.get("gmail_create_draft_ready", True)),
        "gmail_create_draft_blocker": str(payload.get("gmail_create_draft_blocker") or ""),
    }


def prepare_intakes(
    intakes: list[dict[str, Any]],
    paths: AppPaths,
    *,
    render_previews: bool = False,
    allow_duplicate: bool = False,
    allow_existing_draft: bool = False,
    correction_reason: str = "",
    packet_mode: bool = False,
) -> dict[str, Any]:
    if not intakes:
        raise IntakeError("At least one intake is required.")

    normalized_correction_reason = str(correction_reason or "").strip()
    correction_mode = bool(normalized_correction_reason)
    profile = load_json(paths.profile)
    email_config = load_json(paths.email_config)
    court_directory = read_json_list(paths.court_emails)
    draft_log = load_draft_log(paths.draft_log)
    intake_paths = planned_intake_paths(intakes, paths)
    seen_keys: dict[tuple[str, str, str], Path] = {}
    lifecycle_checks: list[dict[str, Any]] = []

    if correction_mode:
        for intake in intakes:
            lifecycle = draft_lifecycle_for_intake(intake, paths)
            lifecycle_checks.append(lifecycle)
            if not lifecycle["replacement_allowed"]:
                raise IntakeError(
                    "Correction mode requires an existing active/drafted request for the same case/date/period, "
                    f"and cannot replace sent requests. {lifecycle['message']}"
                )

    effective_allow_duplicate = bool(allow_duplicate or correction_mode)
    effective_allow_existing_draft = bool(allow_existing_draft or correction_mode)

    for intake_path, intake in zip(intake_paths, intakes):
        key = validate_intake_before_generation(
            intake_path,
            intake,
            profile=profile,
            email_config=email_config,
            court_directory=court_directory,
            duplicate_index=paths.duplicate_index,
            draft_log=draft_log,
            allow_duplicate=effective_allow_duplicate,
            allow_existing_draft=effective_allow_existing_draft,
            correction_reason=normalized_correction_reason,
        )
        if key in seen_keys:
            raise IntakeError(f"Duplicate request appears more than once in this batch: {intake_path} duplicates {seen_keys[key]}")
        seen_keys[key] = intake_path

    if packet_mode:
        validate_packet_recipients(intakes, email_config, court_directory)

    write_intake_files(intakes, intake_paths)

    effective_render_previews = render_previews
    preview_warning = ""
    if render_previews and not shutil.which("pdftoppm"):
        effective_render_previews = False
        preview_warning = "pdftoppm is not available; PDF generated without PNG preview."

    items = [
        prepare_one(
            intake_path,
            profile=profile,
            email_config=email_config,
            court_directory=court_directory,
            template_path=paths.template,
            duplicate_index=paths.duplicate_index,
            output_dir=paths.output_dir,
            html_dir=paths.html_dir,
            draft_output_dir=paths.draft_output_dir,
            render_dir=paths.render_dir,
            draft_log=draft_log,
            allow_duplicate=effective_allow_duplicate,
            allow_existing_draft=effective_allow_existing_draft,
            render_previews=effective_render_previews,
            correction_reason=normalized_correction_reason,
        )
        for intake_path in intake_paths
    ]
    if correction_mode:
        for item, lifecycle in zip(items, lifecycle_checks):
            item["correction_mode"] = True
            item["correction_reason"] = normalized_correction_reason
            item["draft_lifecycle"] = lifecycle
    for item in items:
        previews = item.get("png_previews") or []
        item["png_preview_urls"] = [
            artifact_url_for_path(preview, paths)
            for preview in previews
            if artifact_url_for_path(preview, paths)
        ]
        item["preview_warning"] = preview_warning
    packet = None
    if packet_mode:
        packet = build_packet_result(
            intakes=intakes,
            items=items,
            paths=paths,
            email_config=email_config,
            court_directory=court_directory,
            render_previews=effective_render_previews,
            preview_warning=preview_warning,
        )
    paths.manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = paths.manifest_dir / f"web-prepared-{timestamp_slug()}.json"
    manifest = {
        "status": "prepared",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "draft_creation_tool": "_create_draft",
        "send_allowed": False,
        "correction_mode": correction_mode,
        "correction_reason": normalized_correction_reason,
        "packet_mode": bool(packet_mode),
        "next_safe_action": prepared_next_safe_action(packet_mode=bool(packet_mode)),
        "items": items,
        "manifest": str(manifest_path.resolve()),
    }
    if packet:
        manifest["packet"] = packet
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _coerce_supersedes(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _record_draft_once(payload: dict[str, Any], paths: AppPaths) -> None:
    status = str(payload.get("status") or "active").strip()
    if status not in LIFECYCLE_STATUSES:
        raise IntakeError(f"Unsupported draft lifecycle status: {status}")
    draft_id = str(payload.get("draft_id") or "").strip()
    message_id = str(payload.get("message_id") or "").strip()
    if not draft_id:
        raise IntakeError("Missing required field: draft_id")
    if not message_id:
        raise IntakeError("Missing required field: message_id")

    args = [
        "--draft-id", draft_id,
        "--message-id", message_id,
        "--log", str(paths.draft_log),
        "--duplicate-index", str(paths.duplicate_index),
        "--status", status,
    ]
    payload_path = str(payload.get("payload") or "").strip()
    if payload_path:
        args.extend(["--payload", str(Path(payload_path).resolve())])
    else:
        direct_fields = {
            "--case-number": payload.get("case_number"),
            "--service-date": payload.get("service_date"),
            "--service-period-label": payload.get("service_period_label"),
            "--service-start-time": payload.get("service_start_time"),
            "--service-end-time": payload.get("service_end_time"),
            "--recipient": payload.get("recipient") or payload.get("recipient_email"),
            "--pdf": payload.get("pdf"),
        }
        for flag, value in direct_fields.items():
            if value not in (None, ""):
                args.extend([flag, str(value)])
        draft_payload = str(payload.get("draft_payload") or "").strip()
        if draft_payload and Path(draft_payload).exists():
            args.extend(["--draft-payload", draft_payload])
    thread_id = str(payload.get("thread_id") or "").strip()
    if thread_id:
        args.extend(["--thread-id", thread_id])
    sent_date = str(payload.get("sent_date") or "").strip()
    if sent_date:
        args.extend(["--sent-date", sent_date])
    superseded_by = str(payload.get("superseded_by") or "").strip()
    if superseded_by:
        args.extend(["--superseded-by", superseded_by])
    for draft_id in _coerce_supersedes(payload.get("supersedes")):
        args.extend(["--supersedes", draft_id])
    notes = str(payload.get("notes") or "").strip()
    if notes:
        args.extend(["--notes", notes])

    code = record_gmail_draft_main(args)
    if code != 0:
        raise IntakeError("Could not record Gmail draft. Check payload path and draft/message IDs.")


def _payload_from_existing_draft(record: dict[str, Any], *, status: str, superseded_by: str = "", notes: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case_number": record.get("case_number", ""),
        "service_date": record.get("service_date", ""),
        "service_period_label": record.get("service_period_label", ""),
        "service_start_time": record.get("service_start_time", ""),
        "service_end_time": record.get("service_end_time", ""),
        "recipient": record.get("recipient", ""),
        "pdf": record.get("pdf", ""),
        "draft_payload": record.get("draft_payload", ""),
        "draft_id": record.get("draft_id", ""),
        "message_id": record.get("message_id", ""),
        "thread_id": record.get("thread_id", ""),
        "status": status,
        "superseded_by": superseded_by,
        "notes": notes,
    }
    draft_payload_path = str(payload.get("draft_payload") or "").strip()
    if draft_payload_path and Path(draft_payload_path).exists():
        payload["payload"] = draft_payload_path
    return payload


def duplicate_key_payload(record: dict[str, Any]) -> dict[str, str]:
    case_number, service_date, period = request_identity_key(record)
    return {
        "case_number": case_number,
        "service_date": service_date,
        "service_period_label": period,
    }


def _load_draft_payload_for_response(payload: dict[str, Any]) -> dict[str, Any]:
    payload_path = str(payload.get("payload") or "").strip()
    if not payload_path:
        return {}
    try:
        loaded = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def recorded_duplicate_keys(payload: dict[str, Any], loaded_payload: dict[str, Any]) -> list[dict[str, str]]:
    underlying = payload.get("underlying_requests") or loaded_payload.get("underlying_requests") or []
    if isinstance(underlying, list) and underlying:
        return [
            duplicate_key_payload(request)
            for request in underlying
            if isinstance(request, dict) and request.get("case_number") and request.get("service_date")
        ]
    request = {
        "case_number": payload.get("case_number") or loaded_payload.get("case_number") or "",
        "service_date": payload.get("service_date") or loaded_payload.get("service_date") or "",
        "service_period_label": payload.get("service_period_label") or loaded_payload.get("service_period_label") or "",
    }
    if request["case_number"] and request["service_date"]:
        return [duplicate_key_payload(request)]
    return []


def record_draft(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    supersedes = _coerce_supersedes(payload.get("supersedes"))
    _record_draft_once(payload, paths)
    superseded_drafts: list[str] = []
    if supersedes:
        draft_log = load_draft_log(paths.draft_log)
        existing_by_id = {str(record.get("draft_id") or "").strip(): record for record in draft_log}
        for old_draft_id in supersedes:
            old_record = existing_by_id.get(old_draft_id)
            if not old_record:
                raise IntakeError(f"Cannot supersede unknown draft ID: {old_draft_id}")
            _record_draft_once(
                _payload_from_existing_draft(
                    old_record,
                    status="superseded",
                    superseded_by=str(payload.get("draft_id") or "").strip(),
                    notes=str(payload.get("notes") or "Superseded by corrected draft.").strip(),
                ),
                paths,
            )
            superseded_drafts.append(old_draft_id)

    loaded_payload = _load_draft_payload_for_response(payload)
    service_date = str(payload.get("service_date") or "").strip()
    case_number = str(payload.get("case_number") or "").strip()
    if not service_date or not case_number:
        case_number = case_number or str(loaded_payload.get("case_number") or "")
        service_date = service_date or str(loaded_payload.get("service_date") or "")
    duplicate_keys = recorded_duplicate_keys(payload, loaded_payload)
    thread_id = str(payload.get("thread_id") or "").strip()
    return {
        "status": "recorded",
        "draft_id": str(payload.get("draft_id") or ""),
        "message_id": str(payload.get("message_id") or ""),
        "thread_id": thread_id,
        "superseded_drafts": superseded_drafts,
        "duplicate_key": request_identity_key({
            "case_number": case_number,
            "service_date": service_date,
            "service_period_label": payload.get("service_period_label") or "",
        }) if case_number and service_date else None,
        "duplicate_keys": duplicate_keys,
        "recorded_duplicate_count": len(duplicate_keys),
    }
