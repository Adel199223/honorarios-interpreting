from __future__ import annotations

import copy
import contextlib
import hashlib
import hmac
import json
import mimetypes
import os
import re
import shutil
import secrets
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
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
    file_sha256,
    resolve_email_body,
    resolve_recipient,
    source_email_body,
    validate_draft_payload,
)
from scripts.build_packet_pdf import PacketError, build_packet_pdf
from scripts.create_intake import (
    DEFAULT_SERVICE_PROFILES,
    build_intake,
    current_lisbon_date,
    deep_merge,
    load_profiles,
    remove_empty_values,
)
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
    resolve_json_path,
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
from scripts.record_gmail_draft import main as record_gmail_draft_main, validate_superseded_request_coverage, validate_source_group_history
from scripts.request_identity import normalize_case_number, request_identity_key
from scripts.claim_options import ClaimError, claim_metadata, recorded_travel_requests, validate_shared_travel_groups, validate_travel_payload_groups
from scripts.entity_rules import build_service_place_clause, classify_entity_type, source_mentions_pj_context
from scripts.source_parsing import explicit_service_places, service_date_evidence
from scripts.source_classification import detect_translation_source, format_translation_rejection

from .ai_recovery import ai_status_payload, recover_source_with_openai, text_is_weak_for_pdf_ocr
from .source_cases import source_case_rows, valid_source_case
from .photo_defaults import apply_photo_defaults, load_photo_defaults, preserve_photo_routing, reconcile_photo_venue_edit
from .gmail_draft_api import (
    GmailDraftCreateError,
    create_gmail_draft_from_payload,
    gmail_oauth_callback,
    gmail_oauth_start,
    gmail_status_payload,
    save_gmail_local_config,
    verify_gmail_draft_exists,
)
from .gmail_attempts import attempt_lock, load_attempts, save_attempts, new_attempt, pending_attempt, update_attempt
from .personal_profiles import (
    LEGALPDF_PROFILE_IMPORT_CONFIRMATION_PHRASE,
    apply_profile_defaults_to_intake,
    blank_profile,
    find_profile,
    load_legalpdf_profiles,
    load_profile_store,
    merge_profile_stores,
    missing_required_fields,
    personal_profile_import_report,
    profile_display_name,
    profile_from_mapping,
    profile_summary,
    profile_to_generator_profile,
    save_profile_store,
    validate_profile,
)


# Compatibility exports: browser routes and existing callers keep using services.
from .source_evidence import (
    FIELD_EVIDENCE_LABELS,
    _photo_metadata_date_source,
    build_field_evidence,
    build_profile_evidence,
    build_source_attention,
    combine_text_parts,
    fold_match_text,
)

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
VISIBLE_MONTH_DATE_RE = re.compile(
    r"\b("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"jan(?:eiro)?|fev(?:ereiro)?|mar(?:co|ço)?|abr(?:il)?|mai(?:o)?|jun(?:ho)?|jul(?:ho)?|"
    r"ago(?:sto)?|set(?:embro)?|out(?:ubro)?|nov(?:embro)?|dez(?:embro)?"
    r")\s+(\d{1,2})(?:,?\s+(20\d{2}))?\b",
    re.IGNORECASE,
)
VISIBLE_MONTHS = {
    "jan": 1, "january": 1, "janeiro": 1,
    "feb": 2, "february": 2, "fev": 2, "fevereiro": 2,
    "mar": 3, "march": 3, "marco": 3, "março": 3,
    "apr": 4, "april": 4, "abr": 4, "abril": 4,
    "may": 5, "mai": 5, "maio": 5,
    "jun": 6, "june": 6, "junho": 6,
    "jul": 7, "july": 7, "julho": 7,
    "aug": 8, "august": 8, "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "september": 9, "set": 9, "setembro": 9,
    "oct": 10, "october": 10, "out": 10, "outubro": 10,
    "nov": 11, "november": 11, "novembro": 11,
    "dec": 12, "december": 12, "dez": 12, "dezembro": 12,
}
LEGALPDF_APPLY_REPORT_ID_RE = re.compile(r"^legalpdf-import-apply-[A-Za-z0-9_.-]+$")
AUTO_PROFILE_VALUES = {"", "auto", "auto_detect", "auto-detect", "court_mp_generic"}
LEGALPDF_ADAPTER_CONTRACT_VERSION = "2026-05-10.optional-gmail-boundary.v4"
_GMAIL_CREATE_LOCKS_GUARD = threading.Lock()
_GMAIL_CREATE_LOCKS: dict[str, Any] = {}


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
    gmail_config: Path = ROOT / "config" / "gmail.local.json"
    personal_profiles: Path = ROOT / "config" / "profiles.local.json"
    synthetic_runtime_marker: Path = ROOT / "config" / "synthetic-runtime.local.json"


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
    resolved_path = resolve_json_path(path)
    if not resolved_path.exists():
        return {}
    try:
        data = json.loads(resolved_path.read_text(encoding="utf-8"))
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
        "redirect_uri": redirect_uri or "http://127.0.0.1:8765/api/google-photos/oauth/callback",
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
    """Compatibility entry point for contextual, mixed-format date parsing."""
    return service_date_evidence(text).value


def extract_visible_metadata_date(text: str) -> str:
    compact = COMPACT_DATE_RE.search(text or "")
    if compact:
        year, month, day = compact.groups()
        try:
            return datetime(int(year), int(month), int(day)).date().isoformat()
        except ValueError:
            return ""
    month_match = VISIBLE_MONTH_DATE_RE.search(text or "")
    if not month_match:
        return ""
    month_name, day, year = month_match.groups()
    month = VISIBLE_MONTHS.get(fold_match_text(month_name))
    if not month:
        return ""
    try:
        today = datetime.strptime(app_current_date(), "%Y-%m-%d").date()
    except ValueError:
        today = datetime.now().date()
    inferred_year = int(year) if year else today.year
    try:
        candidate = datetime(inferred_year, int(month), int(day)).date()
    except ValueError:
        return ""
    if not year and (candidate - today).days > 14:
        try:
            candidate = datetime(inferred_year - 1, int(month), int(day)).date()
        except ValueError:
            return ""
    return candidate.isoformat()


def extract_candidate_fields(text: str, paths: AppPaths) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    source_text = text or ""
    case_match = CASE_NUMBER_RE.search(source_text)
    if case_match:
        raw_case = case_match.group(1).strip().rstrip(".").upper()
        fields["raw_case_number"] = raw_case
        fields["source_case_number"] = raw_case
        fields["case_number"] = normalize_case_number(raw_case)

    service_date = extract_first_date(source_text)
    if service_date:
        fields["service_date"] = service_date
        fields["service_date_source"] = "document_text"

    source_emails = {email.lower() for email in EMAIL_RE.findall(source_text)}
    if len(source_emails) == 1:
        fields["recipient_email"] = next(iter(source_emails))

    place_fields, _warning = _source_place_fields(source_text, paths)
    fields.update(place_fields)
    return fields


def _source_place_fields(text: str, paths: AppPaths) -> tuple[dict[str, Any], str]:
    explicit_places = explicit_service_places(text)
    if len(explicit_places) > 1:
        return {}, "Several physical service places appear in the source. Confirm the service building/city and travel destination before PDF creation."
    destinations: list[dict[str, Any]] = []
    if resolve_json_path(paths.known_destinations).exists():
        try:
            loaded = load_known_destinations(paths)
            destinations = loaded if isinstance(loaded, list) else []
        except (IntakeError, json.JSONDecodeError):
            pass
    location_text = explicit_places[0] if explicit_places else text
    normalized_text = fold_match_text(location_text)
    matches: list[tuple[dict[str, Any], str]] = []
    for destination in destinations:
        examples = [*(destination.get("institution_examples") or []), destination.get("destination", "")]
        matched = next((str(example) for example in examples if example and re.search(r"(?<!\w)" + re.escape(fold_match_text(str(example))) + r"(?!\w)", normalized_text)), "")
        if matched:
            matches.append((destination, matched))
    if len(matches) > 1:
        return {}, "Several destination cities appear without one clear service location. Confirm the service building/city and travel destination before PDF creation."
    fields: dict[str, Any] = {}
    if explicit_places:
        fields["service_place"] = explicit_places[0]
        if source_mentions_pj_context({"source_text": text}):
            fields.update(service_entity="Polícia Judiciária", service_entity_type="police", entities_differ=True)
        else:
            entity_type = classify_entity_type(explicit_places[0])
            fields.update(service_entity=explicit_places[0], service_entity_type=entity_type)
            if entity_type in {"gnr", "psp", "police", "other"}:
                fields["entities_differ"] = True
    if matches:
        destination, matched = matches[0]
        fields.setdefault("service_place", matched)
        fields["transport_destination"] = str(destination.get("destination") or matched)
        if destination.get("km_one_way") not in (None, ""):
            fields["km_one_way"] = destination["km_one_way"]
    return fields, ""


def _source_rule_warnings(text: str, paths: AppPaths) -> list[str]:
    date_warning = service_date_evidence(text).warning
    _fields, place_warning = _source_place_fields(text, paths)
    return [warning for warning in (date_warning, place_warning) if warning]


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
    warnings = ai_recovery.get("warnings")
    if isinstance(warnings, list):
        parts.extend(str(item) for item in warnings if str(item).strip())
    return combine_text_parts(*parts)


def _profile_signal_decision(evidence_text: str) -> dict[str, Any]:
    text = fold_match_text(evidence_text)
    actual_places = explicit_service_places(evidence_text)
    if len(actual_places) > 1:
        return {"profile_key": "", "confidence": "low", "reason": "Several physical service places need confirmation; no service-profile defaults were applied.", "signals": [], "allow_fallback": False}
    place_text = fold_match_text(actual_places[0]) if actual_places else text
    signals: list[str] = []

    def has_any(*needles: str) -> bool:
        matched = [needle for needle in needles if fold_match_text(needle) in text]
        signals.extend(matched)
        return bool(matched)

    has_pj = has_any("policia judiciaria", "diretoria do sul", "inspetor", "inspector")
    has_gnr = has_any("guarda nacional republicana", "gnr", "posto territorial", "posto da gnr", "destacamento")
    has_trabalho = has_any("tribunal do trabalho", "juizo do trabalho", "juízo do trabalho", "litigios laborais", "litígios laborais")
    has_medico = has_any("gabinete medico-legal", "gabinete médico-legal", "hospital", "medicina legal", "pericia medico", "perícia médico")
    has_ferreira = has_any("ferreira do alentejo", "gafal")
    def at_service_place(*needles: str) -> bool:
        return any(re.search(r"(?<!\w)" + re.escape(fold_match_text(needle)) + r"(?!\w)", place_text) for needle in needles)

    has_beja = at_service_place("beja", "jafar")
    has_serpa = at_service_place("serpa", "gdsrp")
    has_beringel = at_service_place("beringel", "berinjel", "gcbja")
    has_cuba = at_service_place("cuba", "gacub")
    has_ferreira = at_service_place("ferreira do alentejo", "gafal")
    if not actual_places and sum((has_beja, has_serpa, has_beringel, has_cuba, has_ferreira)) > 1:
        return {"profile_key": "", "confidence": "low", "reason": "Several cities appear without one clear service location. Confirm the service building/city before applying profile defaults.", "signals": signals, "allow_fallback": False}

    if has_pj and has_medico and has_beja:
        return {"profile_key": "pj_medico_legal_beja", "confidence": "high", "reason": "Polícia Judiciária evidence mentions a medical-legal/hospital service.", "signals": signals}
    if has_pj and has_gnr and has_ferreira:
        return {"profile_key": "pj_gnr_ferreira", "confidence": "high", "reason": "Polícia Judiciária evidence mentions the GNR host building in Ferreira do Alentejo.", "signals": signals}
    if has_pj and has_gnr and has_beja:
        return {"profile_key": "pj_gnr_beja", "confidence": "high", "reason": "Polícia Judiciária evidence mentions the GNR host building in Beja.", "signals": signals}
    if has_trabalho:
        beja_labour = re.search(r"\b(?:tribunal|juizo)\s+(?:do|de)\s+trabalho\s+(?:de|em)\s+beja\b", text)
        if beja_labour:
            return {"profile_key": "beja_trabalho", "confidence": "high", "reason": "Evidence names the Tribunal/Juízo do Trabalho de Beja.", "signals": signals}
        return {"profile_key": "", "confidence": "low", "reason": "The labour court is outside the known Beja pattern or its city is missing. Choose the correct payment/service profile; no locality-specific defaults were applied.", "signals": signals, "allow_fallback": False}
    if has_gnr and has_beringel:
        return {"profile_key": "gnr_beringel_beja_mp", "confidence": "high", "reason": "GNR evidence mentions Beringel, which uses Beja Ministério Público payment.", "signals": signals}
    if has_gnr and has_ferreira:
        return {"profile_key": "gnr_ferreira_falentejo", "confidence": "high", "reason": "GNR evidence mentions Ferreira do Alentejo without Polícia Judiciária context.", "signals": signals}
    if has_gnr and has_serpa:
        return {"profile_key": "gnr_serpa_judicial", "confidence": "high", "reason": "GNR evidence mentions Serpa.", "signals": signals}
    if has_gnr and has_cuba:
        return {"profile_key": "gnr_cuba", "confidence": "high", "reason": "GNR evidence mentions Cuba.", "signals": signals}
    if has_pj or actual_places:
        return {"profile_key": "", "confidence": "low", "reason": "The physical service location does not match a known service/payment pattern. Confirm the payment entity and recipient; no profile defaults were applied.", "signals": signals, "allow_fallback": False}
    return {"profile_key": "", "confidence": "low", "reason": "No confident service-profile match was found.", "signals": signals}


def choose_service_profile(
    *,
    requested_profile: str,
    extracted_text: str,
    ai_recovery: dict[str, Any],
    profiles: dict[str, Any],
) -> dict[str, Any]:
    if not profiles:
        raise IntakeError("No service profiles are available. Add a service profile in References before uploading or reviewing a source.")
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

    allow_fallback = suggestion.get("allow_fallback", True)
    fallback_key = "court_mp_generic" if allow_fallback and "court_mp_generic" in profiles else ""
    fallback_reason = str(suggestion.get("reason") or "No confident service-profile match was found.")
    if allow_fallback and not fallback_key and len(profiles) == 1:
        fallback_key = next(iter(profiles))
        fallback_reason += f" Only available service profile {fallback_key!r} was used as a fallback; review its payment entity and recipient before preparing."
    elif allow_fallback and not fallback_key:
        fallback_reason += " Several service profiles are available; choose one explicitly or answer the missing payment and service questions. No profile defaults were applied."

    return {
        "mode": "auto_fallback",
        "profile_key": fallback_key,
        "requested_profile": requested,
        "suggested_profile_key": suggested_key if suggested_is_available else "",
        "confidence": "low",
        "reason": fallback_reason,
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


def _requested_service_profile_from_intake(intake: dict[str, Any]) -> str:
    auto_profile = intake.get("auto_profile")
    requested_from_auto = ""
    if isinstance(auto_profile, dict):
        requested_from_auto = str(auto_profile.get("requested_profile") or "").strip()
    return str(
        intake.get("profile")
        or intake.get("profile_name")
        or intake.get("service_profile_key")
        or requested_from_auto
        or ""
    ).strip()


def _service_profile_defaults(profile_key: str, profiles: dict[str, Any]) -> dict[str, Any]:
    profile = profiles.get(profile_key)
    if not isinstance(profile, dict):
        return {}
    defaults = profile.get("defaults") or {}
    if not isinstance(defaults, dict):
        return {}
    return copy.deepcopy(defaults)


def preserve_review_field_clears(original: dict[str, Any], merged: dict[str, Any]) -> None:
    """Retain deliberate review removals while leaving initial defaults available."""
    allowed = {'case_number', 'service_date', 'photo_metadata_date', 'payment_entity',
               'service_place', 'recipient_email', 'service_period_label',
               'service_start_time', 'service_end_time', 'source_text', 'transport.km_one_way'}
    supplied = original.get('review_cleared_fields')
    if not isinstance(supplied, list):
        return
    active = []
    for field in supplied:
        if not isinstance(field, str) or field not in allowed:
            continue
        transport = original.get('transport') if isinstance(original.get('transport'), dict) else {}
        value = transport.get('km_one_way') if field == 'transport.km_one_way' else original.get(field)
        if str(value if value is not None else '').strip():
            if field == 'service_place':
                entity_type = classify_entity_type(str(value))
                merged.update(service_entity=value, service_entity_type=entity_type,
                              entities_differ=entity_type not in {'court', 'ministerio_publico'},
                              service_place_phrase=build_service_place_clause({'service_place': value}, str(value)))
            elif field == 'payment_entity' and not str(original.get('addressee') or '').strip():
                merged['addressee'] = _default_addressee(str(value))
            continue  # A new field edit or numbered answer resolves the removal.
        active.append(field)
        if field == 'transport.km_one_way':
            if not isinstance(merged.get('transport'), dict):
                merged['transport'] = {}
            merged.setdefault('transport', {})['km_one_way'] = ''
        else:
            merged[field] = ''
        if field == 'service_date':
            merged['photo_metadata_date_requires_confirmation'] = True
        elif field == 'service_place':
            merged.update(service_entity='', service_place_phrase='', service_entity_type='', entities_differ=False)
        elif field == 'payment_entity':
            merged.update(addressee='', recipient_email='', court_email='', court_email_key='',
                          recipient_override_reason='', court_email_override_reason='')
        elif field == 'recipient_email':
            merged.update(court_email='', court_email_key='', recipient_override_reason='', court_email_override_reason='')
    if active:
        merged['review_cleared_fields'] = sorted(set(active))
    else:
        merged.pop('review_cleared_fields', None)


def review_intake_with_profile_evidence(intake: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    """Review an intake and include non-writing service-profile evidence.

    Upload recovery already shows profile decisions and guarded profile proposals.
    This wrapper gives manual/pasted review the same proactive help without
    saving reference data or skipping the normal duplicate/PDF/Gmail guards.
    """
    intake = copy.deepcopy(intake)
    preserve_review_field_clears(intake, intake)
    reconcile_photo_venue_edit(intake)
    _normalize_source_case_confirmation(intake)
    profiles = _load_available_service_profiles(paths)
    requested_profile = _requested_service_profile_from_intake(intake)
    existing_auto = intake.get("auto_profile")
    evidence_text = combine_text_parts(
        str(intake.get("source_text") or ""),
        str(intake.get("notes") or ""),
        str(intake.get("addressee") or ""),
        str(intake.get("payment_entity") or ""),
        str(intake.get("recipient_email") or ""),
        str(intake.get("service_entity") or ""),
        str(intake.get("service_place") or ""),
        str(intake.get("service_place_phrase") or ""),
    )
    ai_recovery = intake.get("ai_recovery") if isinstance(intake.get("ai_recovery"), dict) else {}

    if isinstance(existing_auto, dict) and existing_auto:
        profile_decision = copy.deepcopy(existing_auto)
    else:
        profile_decision = choose_service_profile(
            requested_profile=requested_profile,
            extracted_text=evidence_text,
            ai_recovery=ai_recovery,
            profiles=profiles,
        )

    reviewed_intake = copy.deepcopy(intake)
    if profile_decision.get("auto_applied"):
        profile_key = str(profile_decision.get("profile_key") or "").strip()
        defaults = _service_profile_defaults(profile_key, profiles)
        reviewed_intake = deep_merge(defaults, remove_empty_values(reviewed_intake))
        preserve_photo_routing(intake, reviewed_intake)
        reviewed_intake["service_profile_key"] = profile_key
        reviewed_intake.setdefault("closing_date", app_current_date())
    preserve_review_field_clears(intake, reviewed_intake)
    reviewed_intake["auto_profile"] = profile_decision

    review = review_intake(reviewed_intake, paths)
    candidate = copy.deepcopy(review.get("effective_intake") or reviewed_intake)
    candidate.setdefault("auto_profile", profile_decision)

    deterministic_fields = extract_candidate_fields(str(candidate.get("source_text") or evidence_text), paths)
    metadata = {}
    if str(candidate.get("photo_metadata_date") or "").strip():
        metadata["visible_metadata_date"] = str(candidate.get("photo_metadata_date") or "").strip()
    source_warnings = _source_rule_warnings(str(candidate.get("source_text") or ""), paths)
    profile_proposal = build_profile_proposal(candidate, profile_decision, profiles)
    field_evidence = build_field_evidence(
        candidate=candidate,
        deterministic_fields=deterministic_fields,
        metadata=metadata,
        ai_recovery=ai_recovery,
        profile_decision=profile_decision,
        profiles=profiles,
    )
    review_evidence = {
        "filename": "Manual review",
        "kind": "manual_review",
        "case_number": candidate.get("case_number", ""),
        "raw_case_number": candidate.get("raw_case_number", candidate.get("source_case_number", "")),
        "service_date": candidate.get("service_date", ""),
        "photo_metadata_date": candidate.get("photo_metadata_date", ""),
        "recipient_email": candidate.get("recipient_email", ""),
        "service_place": candidate.get("service_place", ""),
        "question_count": len(review.get("questions") or []),
        "ai_status": ai_recovery.get("status", "not_attempted") if ai_recovery else "not_attempted",
        "ai_attempted": bool(ai_recovery.get("attempted")) if ai_recovery else False,
        "ai_schema_name": ai_recovery.get("schema_name", "") if ai_recovery else "",
        "ai_prompt_version": ai_recovery.get("prompt_version", "") if ai_recovery else "",
        "auto_profile": profile_decision,
        "profile_evidence": build_profile_evidence(profile_decision),
        "field_evidence": field_evidence,
        "attention": build_source_attention(
            candidate=candidate,
            review=review,
            ai_recovery=ai_recovery,
            profile_decision=profile_decision,
            profile_proposal=profile_proposal,
            field_evidence=field_evidence,
            warnings=source_warnings,
        ),
        "profile_proposal": profile_proposal,
        "warnings": source_warnings,
        "rendered_page_urls": [],
        "rendered_page_count": 0,
    }
    return {
        **review,
        "intake": reviewed_intake,
        "auto_profile": profile_decision,
        "profile_proposal": profile_proposal,
        "review_evidence": review_evidence,
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
        "schema_name",
        "prompt_version",
        "raw_visible_text",
        "fields",
        "missing_fields",
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
    date_evidence = service_date_evidence(str(intake.get("source_text") or ""))

    raw_case = _first_ai_field(ai_recovery, "raw_case_number", "source_case_number", "case_number").upper()
    if raw_case and not intake.get("case_number") and valid_source_case(raw_case):
        intake["raw_case_number"] = raw_case
        intake["source_case_number"] = raw_case
        intake["case_number"] = normalize_case_number(raw_case)

    photo_metadata_date = _first_ai_field(ai_recovery, "photo_metadata_date", "metadata_date")
    if photo_metadata_date and _looks_like_iso_date(photo_metadata_date) and not intake.get("photo_metadata_date"):
        intake["photo_metadata_date"] = photo_metadata_date

    service_date = _first_ai_field(ai_recovery, "service_date")
    if date_evidence.value and not intake.get("service_date"):
        intake["service_date"] = date_evidence.value
        intake["service_date_source"] = _service_date_source_for_ai(intake, date_evidence.value)
    if service_date and service_date != date_evidence.value:
        warnings = intake["ai_recovery"].setdefault("warnings", [])
        warnings.append("The AI-suggested date was not supported by one clear service date in the visible text. Check or confirm the service date before PDF creation.")
    if date_evidence.needs_confirmation and "user_confirmed" not in str(intake.get("service_date_source") or ""):
        intake.pop("service_date", None)
        intake.pop("service_date_source", None)

    source_timestamp = _first_ai_field(ai_recovery, "source_document_timestamp", "document_timestamp")
    if source_timestamp and not intake.get("source_document_timestamp"):
        intake["source_document_timestamp"] = source_timestamp

    court_email = _first_ai_field(ai_recovery, "court_email", "recipient_email")
    source_emails = {email.lower() for email in EMAIL_RE.findall(str(intake.get('source_text') or ''))}
    if court_email and _looks_like_email(court_email) and not str(intake.get("recipient_email") or "").strip():
        if len(source_emails) == 1 and court_email.lower() in source_emails:
            intake["recipient_email"] = court_email.lower()
        else:
            intake["ai_recovery"].setdefault("warnings", []).append(
                "The AI-suggested email was not the single visible source email and was not selected. Choose a verified court contact."
            )

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
            # Cameras normally store DateTimeOriginal in the nested Exif IFD.
            # Top-level DateTime is the image modification time, not capture.
            try:
                capture_exif = exif.get_ifd(34665)
            except (KeyError, TypeError, ValueError, OSError):
                capture_exif = {}
            for value in (capture_exif.get(36867), exif.get(36867),
                          capture_exif.get(36868), exif.get(36868)):
                exif_date = parse_exif_date(value)
                if exif_date:
                    metadata["exif_date"] = exif_date
                    break
            warnings: list[str] = []
            if not metadata.get('exif_date') and parse_exif_date(exif.get(306)):
                warnings.append('The image has an EXIF modification date but no capture date. Confirm the actual photo/service date.')
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


def infer_supporting_attachment_kind(filename: str, content_type: str, content: bytes) -> str:
    suffix = Path(filename or "").suffix.lower()
    normalized_content_type = (content_type or "").lower()
    if suffix in PDF_SUFFIXES or normalized_content_type == "application/pdf" or content.lstrip().startswith(b"%PDF"):
        return "notification_pdf"
    if suffix in IMAGE_SUFFIXES or normalized_content_type.startswith("image/"):
        return "photo"
    raise IntakeError("Supporting attachment must be a PDF or image file.")


def store_supporting_attachment_upload(
    *,
    filename: str,
    content_type: str,
    content: bytes,
    paths: AppPaths,
) -> dict[str, Any]:
    attachment_kind = infer_supporting_attachment_kind(filename, content_type or "", content)
    suffix = validate_upload(attachment_kind, filename, content_type or "", content)
    digest = sha256_hex(content)
    safe_name = safe_upload_filename(filename or "supporting-attachment")
    stored_filename = f"{timestamp_slug()}_{digest[:12]}_{safe_name}"
    if not Path(stored_filename).suffix:
        stored_filename = f"{stored_filename}{suffix}"
    stored_path = paths.source_upload_dir / "attachments" / stored_filename
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(content)

    attachment = {
        "source_kind": "supporting_attachment",
        "attachment_kind": attachment_kind,
        "filename": filename or safe_name,
        "stored_path": str(stored_path.resolve()),
        "artifact_url": artifact_url_for_path(stored_path, paths),
        "sha256": digest,
        "size": len(content),
        "content_type": content_type or "",
    }
    return {
        "status": "uploaded",
        "attachment": attachment,
        "message": "Supporting attachment uploaded for review. No PDF, Gmail draft, or local draft record was created.",
        "send_allowed": False,
    }


def _review_source_cases(result: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    candidate = result['candidate_intake']
    rows = source_case_rows(result['extracted_text'], result['ai_recovery']) if result['source']['source_kind'] == 'photo' else []
    if not rows:
        existing_case = str(candidate.get('case_number') or '')
        rows = [{'case_number': existing_case, 'raw_case_number': str(candidate.get('raw_case_number') or existing_case)}]
    case_candidates = []
    for row in rows:
        child = copy.deepcopy(candidate)
        child.update(case_number=row['case_number'], raw_case_number=row['raw_case_number'],
                     source_case_number=row['raw_case_number'])
        child['source_case_numbers'] = [item['case_number'] for item in rows if item['case_number']]
        if not row['case_number']:
            child['case_number_requires_confirmation'] = True
        # Source rows must carry the selected effective profile before UI grouping.
        child, _, _ = effective_intake_for_profile(child, paths)
        child_review = review_intake(child, paths)
        child = copy.deepcopy(child_review.get('effective_intake') or child)
        evidence = build_field_evidence(
            candidate=child, deterministic_fields=extract_candidate_fields(result['extracted_text'], paths),
            metadata=result['source']['metadata'], ai_recovery=result['ai_recovery'],
            profile_decision=child.get('auto_profile') or {}, profiles=_load_available_service_profiles(paths),
        )
        proposal = build_profile_proposal(child, child.get('auto_profile') or {}, _load_available_service_profiles(paths))
        attention = build_source_attention(candidate=child, review=child_review, ai_recovery=result['ai_recovery'],
            profile_decision=child.get('auto_profile') or {}, profile_proposal=proposal,
            field_evidence=evidence, warnings=result['source_evidence'].get('warnings') or [])
        child_review['review_evidence'] = {**copy.deepcopy(result['source_evidence']),
            'case_number': child.get('case_number', ''), 'raw_case_number': child.get('raw_case_number', ''),
            'question_count': len(child_review.get('questions') or []), 'field_evidence': evidence,
            'attention': attention, 'profile_proposal': proposal}
        child_review['profile_proposal'] = proposal
        case_candidates.append({'candidate_intake': child, 'review': child_review})
    result['case_count'] = len(case_candidates)
    result['case_candidates'] = case_candidates
    result['candidate_intake'] = case_candidates[0]['candidate_intake']
    result['review'] = case_candidates[0]['review']
    # Preserve source-upload evidence while making the selected case coherent.
    evidence = copy.deepcopy(case_candidates[0]['review']['review_evidence'])
    selected = result['candidate_intake']
    evidence.update(case_number=selected.get('case_number', ''), raw_case_number=selected.get('raw_case_number', ''),
                    case_count=len(case_candidates), case_numbers=selected.get('source_case_numbers', []),
                    question_count=len(result['review'].get('questions') or []),
                    field_evidence=case_candidates[0]['review']['review_evidence']['field_evidence'])
    result['source_evidence'] = evidence
    result['profile_proposal'] = case_candidates[0]['review']['profile_proposal']
    return result


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


def _load_available_service_profiles(paths: AppPaths) -> dict[str, Any]:
    try:
        profiles = load_profiles(paths.service_profiles)
    except FileNotFoundError as exc:
        raise IntakeError("Service profiles are missing. Add a service profile in References or restore the configured service-profile file before uploading or reviewing a source.") from exc
    if not profiles:
        raise IntakeError("No service profiles are available. Add a service profile in References before uploading or reviewing a source.")
    return profiles


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
    contact_text: str | None = None,
) -> dict[str, Any]:
    profiles = _load_available_service_profiles(paths)
    selected_profile = str(profile_name or "").strip()
    if not selected_profile:
        selected_profile = str(choose_service_profile(requested_profile="", extracted_text=extracted_text, ai_recovery={}, profiles=profiles)["profile_key"])
    profile = profiles.get(selected_profile) if selected_profile else {}
    if selected_profile and not isinstance(profile, dict):
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
    # Consider both independent text and recovered visible text before choosing
    # a source contact. Saved profile contacts are retained when sources conflict.
    if contact_text is not None and len({email.lower() for email in EMAIL_RE.findall(contact_text)}) > 1:
        fields.pop('recipient_email', None)
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
    personal_profile_id: str = "",
    visible_text: str = "",
    ai_recovery_mode: str = "auto",
    paths: AppPaths,
) -> dict[str, Any]:
    suffix = validate_upload(source_kind, filename, content_type or "", content)
    profiles = _load_available_service_profiles(paths)
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
    visible_metadata_context = "\n".join(part for part in [filename, visible_text.strip()] if part)
    visible_metadata_date = extract_visible_metadata_date(visible_metadata_context)
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

    deterministic_fields = extract_candidate_fields(extracted_text, paths)
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
    profile_decision = choose_service_profile(
        requested_profile=profile_name,
        extracted_text=extracted_text,
        ai_recovery=ai_recovery,
        profiles=profiles,
    )
    candidate = build_partial_intake_from_profile(
        profile_name=str(profile_decision.get("profile_key") or ""),
        source_kind=source_kind,
        filename=filename,
        stored_path=stored_path,
        digest=digest,
        extracted_text=extracted_text,
        metadata=metadata,
        paths=paths,
        contact_text=combine_text_parts(extracted_text, str(ai_recovery.get('raw_visible_text') or '')),
    )
    candidate = merge_ai_recovery_into_intake(candidate, ai_recovery)
    apply_photo_defaults(
        candidate, preferences=load_photo_defaults(paths.ai_config), metadata=metadata,
        ai_recovery=ai_recovery, directory=read_json_list(paths.court_emails),
        explicit_profile=profile_decision.get('mode') == 'explicit_profile',
    )
    if (
        str(candidate.get("photo_metadata_date") or "").strip()
        and not str(candidate.get("service_date") or "").strip()
    ):
        # EXIF and visible capture dates are source evidence. An uploaded photo
        # without a document service date still needs the user's date choice.
        candidate["photo_metadata_date_requires_confirmation"] = True
    if str(personal_profile_id or "").strip():
        candidate["personal_profile_id"] = str(personal_profile_id or "").strip()
    candidate["auto_profile"] = profile_decision
    profile_proposal = build_profile_proposal(candidate, profile_decision, profiles)
    review = review_intake(candidate, paths)
    combined_text = str(candidate.get("source_text") or extracted_text or "").strip()
    field_evidence = build_field_evidence(
        candidate=candidate,
        deterministic_fields=deterministic_fields,
        metadata=metadata,
        ai_recovery=ai_recovery,
        profile_decision=profile_decision,
        profiles=profiles,
    )
    profile_evidence = build_profile_evidence(profile_decision)

    source_warnings = [
        *[str(item) for item in metadata.get("warnings", []) if str(item).strip()],
        *[str(item) for item in candidate.get("ai_recovery", {}).get("warnings", []) if str(item).strip()],
        *_source_rule_warnings(combined_text, paths),
    ]
    source_attention = build_source_attention(
        candidate=candidate,
        review=review,
        ai_recovery=ai_recovery,
        profile_decision=profile_decision,
        profile_proposal=profile_proposal,
        field_evidence=field_evidence,
        warnings=source_warnings,
    )

    result = {
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
            "ai_schema_name": ai_recovery.get("schema_name", ""),
            "ai_prompt_version": ai_recovery.get("prompt_version", ""),
            "auto_profile": profile_decision,
            "profile_evidence": profile_evidence,
            "field_evidence": field_evidence,
            "attention": source_attention,
            "profile_proposal": profile_proposal,
            "warnings": source_warnings,
            "rendered_page_urls": [item["artifact_url"] for item in metadata.get("rendered_pages", [])],
            "rendered_page_count": metadata.get("rendered_page_count", 0),
        },
        "send_allowed": False,
    }
    return _review_source_cases(result, paths)


def read_json_list(path: Path) -> list[dict[str, Any]]:
    resolved_path = resolve_json_path(path)
    if not resolved_path.exists():
        return []
    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise IntakeError(f"Expected a JSON list at {resolved_path}")
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


def _destination_upsert_context(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
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
    change = reference_change_payload(
        reference_kind="destination",
        record_key=record["destination"],
        before=copy.deepcopy(existing) if existing is not None else None,
        after=record,
        reason=str(payload.get("change_reason") or ""),
    )
    return {
        "records": records,
        "existing_index": existing_index,
        "existing": existing,
        "record": record,
        "reference_change": change,
    }


def preview_known_destination_upsert(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    context = _destination_upsert_context(payload, paths)
    return {
        "status": "preview",
        "kind": "destination",
        "record": context["record"],
        "reference_change": context["reference_change"],
        "write_allowed": False,
        "send_allowed": False,
    }


def upsert_known_destination(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    context = _destination_upsert_context(payload, paths)
    records = context["records"]
    existing_index = context["existing_index"]
    record = context["record"]
    if existing_index is None:
        records.append(record)
    else:
        records[existing_index] = record
    write_json_list(paths.known_destinations, records)
    change = context["reference_change"]
    if change.get("changes"):
        append_profile_change_log(change, paths)
    return {
        "status": "saved",
        "kind": "destination",
        "record": record,
        "reference_change": change,
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


def _court_email_upsert_context(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
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
    change = reference_change_payload(
        reference_kind="court_email",
        record_key=record["key"],
        before=copy.deepcopy(existing) if existing is not None else None,
        after=record,
        reason=str(payload.get("change_reason") or ""),
    )
    return {
        "records": records,
        "existing_index": existing_index,
        "existing": existing,
        "record": record,
        "reference_change": change,
    }


def preview_court_email_upsert(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    context = _court_email_upsert_context(payload, paths)
    return {
        "status": "preview",
        "kind": "court_email",
        "record": context["record"],
        "reference_change": context["reference_change"],
        "write_allowed": False,
        "send_allowed": False,
    }


def upsert_court_email(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    context = _court_email_upsert_context(payload, paths)
    records = context["records"]
    existing_index = context["existing_index"]
    record = context["record"]
    if existing_index is None:
        records.append(record)
    else:
        records[existing_index] = record
    write_json_list(paths.court_emails, records)
    change = context["reference_change"]
    if change.get("changes"):
        append_profile_change_log(change, paths)
    return {
        "status": "saved",
        "kind": "court_email",
        "record": record,
        "reference_change": change,
        "count": len(records),
        "send_allowed": False,
    }


def write_json_object(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


BACKUP_SCHEMA_VERSION = 1
BACKUP_KIND = "honorarios_local_backup"
BACKUP_RECENT_SECONDS = 24 * 60 * 60
LOCAL_BACKUP_RESTORE_PHRASE = "RESTORE LOCAL HONORARIOS BACKUP"


def backup_dataset_paths(paths: AppPaths) -> dict[str, tuple[Path, type]]:
    return {
        "personal_profiles": (paths.personal_profiles, dict),
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


def diagnostics_status_payload() -> dict[str, Any]:
    checks = [
        {
            "key": "default_live_smoke",
            "label": "Default live smoke",
            "description": "Checks the LegalPDF-style landmarks, draft-only API contract, AI/Google Photos status, public readiness, and diagnostics status.",
            "command_template": "python scripts/local_app_smoke.py --base-url {base_url} --json",
            "effect": "read_only",
            "writes": "none",
        },
        {
            "key": "source_upload_smoke",
            "label": "Source upload smoke",
            "description": "Uploads disposable synthetic photo/PDF sources through the API and checks Source Evidence plus Review Attention without preparing artifacts.",
            "command_template": "python scripts/local_app_smoke.py --base-url {base_url} --source-upload-checks --json",
            "effect": "synthetic_upload_only",
            "writes": "synthetic source-preview artifacts only",
        },
        {
            "key": "supporting_attachment_smoke",
            "label": "Supporting attachment smoke",
            "description": "Uploads a disposable synthetic declaration/proof PDF through the attachment API and checks it remains evidence-only.",
            "command_template": "python scripts/local_app_smoke.py --base-url {base_url} --supporting-attachment-checks --json",
            "effect": "synthetic_upload_only",
            "writes": "synthetic supporting-attachment artifact only",
        },
        {
            "key": "runtime_doctor",
            "label": "Python runtime doctor",
            "description": "Read-only dependencies check for the active Python runtime before running browser, adapter, or Gmail smoke commands.",
            "command_template": "python scripts/runtime_doctor.py --json",
            "effect": "read_only_runtime_dependencies",
            "writes": "none",
        },
        {
            "key": "isolated_source_upload_smoke",
            "label": "Isolated source upload smoke",
            "description": "Runs the same upload evidence checks in a temporary synthetic runtime so private local data and output folders are untouched.",
            "command_template": "python scripts/isolated_app_smoke.py --source-upload-checks --json",
            "effect": "temporary_isolated_runtime",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "isolated_supporting_attachment_smoke",
            "label": "Isolated supporting attachment smoke",
            "description": "Runs declaration/proof attachment evidence checks in a temporary synthetic runtime so private source-upload folders stay untouched.",
            "command_template": "python scripts/isolated_app_smoke.py --supporting-attachment-checks --json",
            "effect": "temporary_isolated_runtime",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "legalpdf_adapter_readiness",
            "label": "LegalPDF adapter readiness",
            "description": "Read-only first check for future LegalPDF callers: validates /api/health and the adapter contract without uploading, preparing PDFs, recording drafts, or calling Gmail.",
            "command_template": "python scripts/legalpdf_adapter_caller.py --base-url {base_url} --readiness-only --json",
            "effect": "read_only_adapter_readiness",
            "writes": "none",
        },
        {
            "key": "isolated_adapter_contract_smoke",
            "label": "LegalPDF adapter contract smoke",
            "description": "Runs the future LegalPDF caller sequence in a temporary synthetic runtime: source upload, numbered-answer review recovery, packet preflight, prepare, stale prepared-review rejection, Manual Draft Handoff, and local draft recording with no Gmail network call.",
            "command_template": "python scripts/isolated_app_smoke.py --adapter-contract-checks --json",
            "effect": "temporary_isolated_runtime_adapter_contract",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "isolated_gmail_api_smoke",
            "label": "Advanced/future Gmail Draft API smoke",
            "description": "Advanced future OAuth path check: runs fake Gmail drafts.create against a temporary synthetic runtime, verifies local draft-log and duplicate-index updates, then checks a read-only reconciliation mismatch without contacting Google. The recommended daily path remains Manual Draft Handoff.",
            "command_template": "python scripts/isolated_app_smoke.py --gmail-api-checks --json",
            "effect": "temporary_isolated_runtime_fake_gmail",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "browser_iab_smoke",
            "label": "Browser/IAB review smoke",
            "description": "Uses the Codex in-app Browser runner for the review drawer and batch UI path without local file uploads.",
            "command_template": "python scripts/local_app_smoke.py --base-url {base_url} --browser-click-through --browser-iab-click-through --json",
            "effect": "browser_ui_only",
            "writes": "none",
        },
        {
            "key": "browser_iab_upload_smoke",
            "label": "Browser/IAB upload smoke",
            "description": "Uses the Codex in-app Browser runner to try disposable local photo/PDF upload evidence; reports a clean tooling blocker when safe file-input support is unavailable.",
            "command_template": "python scripts/local_app_smoke.py --base-url {base_url} --browser-click-through --browser-iab-click-through --browser-upload-photo --browser-upload-pdf --json",
            "effect": "browser_ui_only",
            "writes": "synthetic source-preview artifacts only",
        },
        {
            "key": "browser_iab_supporting_attachment_smoke",
            "label": "Browser/IAB attachment smoke",
            "description": "Uses the Codex in-app Browser runner to upload a disposable declaration through the Supporting proof UI and verify it remains evidence-only.",
            "command_template": "python scripts/local_app_smoke.py --base-url {base_url} --browser-click-through --browser-iab-click-through --browser-upload-supporting-attachment --json",
            "effect": "browser_synthetic_upload_only",
            "writes": "synthetic supporting-attachment artifact only",
        },
        {
            "key": "browser_iab_answer_apply_smoke",
            "label": "Browser/IAB answers and apply history smoke",
            "description": "Runs the Codex in-app Browser runner against an isolated runtime, applies compact numbered answers, and checks LegalPDF Apply History, Detail, and read-only Restore Plan surfaces without preparing PDFs or writing local records.",
            "command_template": "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-answer-questions --browser-apply-history --json",
            "effect": "temporary_isolated_runtime_browser_ui",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "browser_iab_supporting_attachment_stale_smoke",
            "label": "Browser/IAB Supporting proof stale smoke",
            "description": "Runs the Codex in-app Browser runner against an isolated runtime, prepares a synthetic replacement, builds the Manual Draft Handoff packet, then uploads a Supporting proof and verifies prepared Gmail surfaces go stale.",
            "command_template": "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-correction-mode --browser-prepare-replacement --browser-supporting-attachment-stale --json",
            "effect": "temporary_isolated_runtime_browser_artifacts",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "browser_iab_record_helper_smoke",
            "label": "Browser/IAB record helper smoke",
            "description": "Runs the Codex in-app Browser runner against an isolated runtime, prepares a synthetic replacement, parses fake Gmail _create_draft IDs, proves the handoff checklist gates one-click recording, and autofills local record fields without recording or calling Gmail.",
            "command_template": "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-correction-mode --browser-prepare-replacement --browser-record-helper --json",
            "effect": "temporary_isolated_runtime_browser_artifacts",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "python_browser_record_helper_smoke",
            "label": "Python browser record helper smoke",
            "description": "Runs the optional Python Playwright browser runner against an isolated runtime, prepares a synthetic replacement, parses fake Gmail _create_draft IDs, proves the handoff checklist gates one-click recording, and autofills local record fields without recording or calling Gmail.",
            "command_template": "python scripts/isolated_app_smoke.py --browser-click-through --browser-correction-mode --browser-prepare-replacement --browser-record-helper --json",
            "effect": "temporary_isolated_runtime_python_browser_artifacts",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "browser_iab_profile_proposal_smoke",
            "label": "Browser/IAB profile proposal smoke",
            "description": "Uses the Codex in-app Browser runner to recover an unknown recurring pattern, preview the proposed Service profile in the guarded editor, and verify LegalPDF import gates without saving.",
            "command_template": "python scripts/local_app_smoke.py --base-url {base_url} --browser-click-through --browser-iab-click-through --browser-profile-proposal --json",
            "effect": "browser_ui_only",
            "writes": "none",
        },
        {
            "key": "browser_iab_recent_work_lifecycle_smoke",
            "label": "Browser/IAB Recent Work lifecycle smoke",
            "description": "Runs the Codex in-app Browser runner against an isolated seeded draft history and verifies Recent Work lifecycle controls without clicking Gmail verify or local status writes.",
            "command_template": "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-recent-work-lifecycle --json",
            "effect": "temporary_isolated_runtime_browser_ui",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "browser_iab_recent_work_reconciliation_smoke",
            "label": "Browser/IAB Recent Work reconciliation smoke",
            "description": "Runs the Codex in-app Browser runner against an isolated seeded draft history with fake Gmail mode, clicks the Recent Work read-only verify action, and checks users.drafts.get not_found reconciliation without local status writes.",
            "command_template": "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-recent-work-reconciliation --json",
            "effect": "temporary_isolated_runtime_fake_gmail_browser",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "browser_iab_manual_handoff_stale_smoke",
            "label": "Browser/IAB Manual Draft Handoff stale smoke",
            "description": "Runs the Codex in-app Browser runner against an isolated runtime, prepares a synthetic replacement, builds the Manual Draft Handoff packet, then verifies intake changes clear stale handoff and record-helper state.",
            "command_template": "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-correction-mode --browser-prepare-replacement --browser-manual-handoff-stale --json",
            "effect": "temporary_isolated_runtime_browser_artifacts",
            "writes": "temporary synthetic runtime only",
        },
        {
            "key": "browser_iab_gmail_api_smoke",
            "label": "Browser/IAB fake Gmail Draft API smoke",
            "description": "Runs the Codex in-app Browser runner against an isolated runtime with fake Gmail mode, creates a synthetic draft through users.drafts.create, then verifies it read-only through users.drafts.get without contacting Google.",
            "command_template": "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-gmail-api-create --json",
            "effect": "temporary_isolated_runtime_fake_gmail_browser",
            "writes": "temporary synthetic runtime only",
        },
    ]
    return {
        "status": "ready",
        "message": "Local diagnostics are available. Start with the source upload smoke after changing upload, recovery, Source Evidence, or Review Attention behavior.",
        "recommended_next_check": "source_upload_smoke",
        "gmail_action": "_create_draft",
        "draft_only": True,
        "send_allowed": False,
        "write_allowed": False,
        "managed_data_changed": False,
        "checks": checks,
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
        "restore_requirements": {
            "confirmation_phrase": LOCAL_BACKUP_RESTORE_PHRASE,
            "required_fields": ["confirm_restore", "confirmation_phrase", "restore_reason"],
        },
        "write_allowed": False,
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


def legalpdf_adapter_contract(paths: AppPaths) -> dict[str, Any]:
    """Return the read-only integration boundary for a future LegalPDF adapter."""
    return {
        "status": "ready",
        "contract_version": LEGALPDF_ADAPTER_CONTRACT_VERSION,
        "generated_on": app_current_date(),
        "purpose": "Stable read-only contract for a future LegalPDF Translate caller to use this standalone honorários workflow without copying internals.",
        "documentation": "docs/legalpdf-adapter-contract.md",
        "standalone_app": "LegalPDF Honorários",
        "legalpdf_write_allowed": False,
        "write_allowed": False,
        "send_allowed": False,
        "draft_only": True,
        "managed_data_changed": False,
        "recommended_gmail_mode": "manual_handoff",
        "gmail_boundary": {
            "primary": "Build a Manual Draft Handoff packet from a prepared payload, create the Gmail draft outside this app, then record returned draft identifiers locally after the handoff checklist is reviewed.",
            "optional_later": "When OAuth is connected, this app may create drafts through its guarded Gmail Draft API path. This contract does not require that path.",
            "required_tool": "_create_draft",
            "attachment_files_shape": "array_of_absolute_existing_paths",
            "local_recording_requires_reviewed_handoff": True,
            "draft_only": True,
            "send_allowed": False,
        },
        "optional_gmail_draft_api_boundary": {
            "status": "optional",
            "purpose": "Describe the in-app OAuth path for callers that intentionally choose this app's guarded Gmail Draft API helper instead of Manual Draft Handoff.",
            "create_endpoint": "/api/gmail/drafts/create",
            "verify_endpoint": "/api/gmail/drafts/verify",
            "create_action": "users.drafts.create",
            "verify_action": "users.drafts.get",
            "required_fields_source": "prepared_review_binding.gmail_api_create_required_fields",
            "requires_current_prepared_review": True,
            "requires_gmail_handoff_reviewed": True,
            "records_local_draft_after_create": True,
            "blocks_duplicates_before_gmail_call": True,
            "verify_read_only": True,
            "verify_local_records_changed": False,
            "draft_only": True,
            "send_allowed": False,
            "forbidden_actions": [
                "users.messages.send",
                "users.drafts.send",
                "users.messages.trash",
                "users.messages.delete",
                "users.messages.list",
                "users.drafts.delete",
            ],
        },
        "prepared_review_binding": {
            "purpose": "Bind preflight, prepared artifacts, Manual Draft Handoff, Gmail Draft API creation, and fast local recording to the same reviewed payload/manifest fingerprint.",
            "preflight_response_field": "preflight_review",
            "prepare_request_field": "preflight_review",
            "prepare_response_field": "prepared_review",
            "handoff_required_fields": [
                "payload",
                "prepared_manifest",
                "prepared_review_token",
                "review_fingerprint",
            ],
            "record_required_fields": [
                "payload",
                "prepared_manifest",
                "prepared_review_token",
                "review_fingerprint",
                "gmail_handoff_reviewed",
                "draft_id",
                "message_id",
                "thread_id",
            ],
            "gmail_api_create_required_fields": [
                "payload",
                "prepared_manifest",
                "prepared_review_token",
                "review_fingerprint",
                "gmail_handoff_reviewed",
            ],
            "stale_after_payload_or_manifest_change": True,
            "local_workflow_guard_only": True,
            "send_allowed": False,
        },
        "sequence": [
            {
                "step": 1,
                "name": "recover_source_or_start_blank",
                "endpoint": "/api/sources/upload",
                "method": "POST",
                "required_request_fields": ["file", "source_kind"],
                "response_fields": ["status", "candidate_intake", "source_evidence"],
                "effect": "stores source evidence in this app only",
                "notes": "Use local PDF/photo upload evidence or manual entry. LegalPDF should not write its own honorários files directly.",
            },
            {
                "step": 2,
                "name": "review_intake",
                "endpoint": "/api/review",
                "method": "POST",
                "required_request_fields": ["intake"],
                "response_fields": ["status", "effective_intake", "questions", "question_text", "draft_text"],
                "effect": "read_only",
                "notes": "Classifies translation set-asides, applies profile/default evidence, returns Portuguese draft text and numbered questions.",
            },
            {
                "step": 3,
                "name": "apply_numbered_answers_when_needed",
                "endpoint": "/api/review/apply-answers",
                "method": "POST",
                "required_request_fields": ["intake", "answers"],
                "response_fields": ["status", "effective_intake", "applied_fields", "draft_text"],
                "effect": "read_only_intake_update_in_request_context",
                "notes": "Compact answers rerun normal review and do not bypass duplicates, date conflicts, recipient checks, or draft-only safeguards.",
            },
            {
                "step": 4,
                "name": "check_batch_preflight",
                "endpoint": "/api/prepare/preflight",
                "method": "POST",
                "required_request_fields": ["intakes", "packet_mode"],
                "response_fields": [
                    "preflight_review.review_fingerprint",
                    "preflight_review.preflight_review_token",
                ],
                "effect": "read_only",
                "notes": "Validate all queued requests before any PDF, payload, manifest, or draft record is written.",
            },
            {
                "step": 5,
                "name": "prepare_artifacts",
                "endpoint": "/api/prepare",
                "method": "POST",
                "required_request_fields": ["intakes", "packet_mode", "preflight_review"],
                "response_fields": [
                    "prepared_review.manifest",
                    "prepared_review.prepared_review_token",
                    "prepared_review.review_fingerprint",
                    "prepared_review.payload_paths",
                    "items[].draft_payload",
                    "packet.draft_payload",
                ],
                "effect": "writes_this_app_output_only",
                "notes": "Creates PDFs, PNG previews when available, manifests, and draft payloads after review/preflight succeeds.",
            },
            {
                "step": 6,
                "name": "build_manual_handoff_packet",
                "endpoint": "/api/gmail/manual-handoff",
                "method": "POST",
                "required_request_fields": [
                    "payload",
                    "prepared_manifest",
                    "prepared_review_token",
                    "review_fingerprint",
                ],
                "response_fields": ["status", "copyable_prompt", "attachment_files", "attachment_sha256"],
                "effect": "read_only",
                "notes": "Reloads and validates the prepared payload, then returns copy-ready draft-only handoff text with attachment names and hashes.",
            },
            {
                "step": 7,
                "name": "record_created_draft",
                "endpoint": "/api/drafts/record",
                "method": "POST",
                "required_request_fields": [
                    "payload",
                    "prepared_manifest",
                    "prepared_review_token",
                    "review_fingerprint",
                    "gmail_handoff_reviewed",
                    "draft_id",
                    "message_id",
                    "thread_id",
                ],
                "response_fields": ["status", "draft_id", "message_id", "thread_id", "recorded_duplicate_count"],
                "effect": "writes_this_app_duplicate_and_draft_logs",
                "notes": "Use only after the Gmail draft exists and the PDF preview plus exact draft args were reviewed.",
            },
        ],
        "caller_responsibilities": [
            "Treat prepared artifacts as stale after any source, review, profile, queue, packet-mode, or intake change.",
            "Show numbered missing questions to the user and rerun review after answers.",
            "Stop for translation or word-count sources instead of generating an interpreting request.",
            "Stop for metadata/document date conflicts unless the date is explicitly user-confirmed.",
            "Respect duplicate-index and active-draft blockers; use correction mode only with a short reason.",
            "Use packet underlying_requests when one Gmail draft covers multiple requerimentos.",
            "Never write to LegalPDF Translate from this app contract.",
        ],
        "authoritative_sources": [
            "this_project_pdf_generator",
            "this_project_duplicate_index",
            "this_project_service_profiles",
            "this_project_personal_profiles",
            "this_project_gmail_draft_payload_validator",
        ],
        "forbidden_capabilities": [
            "gmail_message_sending",
            "gmail_draft_sending",
            "gmail_trash_or_delete",
            "gmail_mailbox_search",
            "legalpdf_translate_writes",
            "direct_duplicate_index_bypass",
            "direct_pdf_generation_without_review",
        ],
        "safety_flags": {
            "translation_set_aside_before_questions": True,
            "numbered_questions_required": True,
            "metadata_conflicts_block_generation": True,
            "duplicates_block_generation": True,
            "active_drafts_block_generation_without_correction": True,
            "packet_underlying_requests_required": True,
            "manual_handoff_primary_when_gmail_oauth_disconnected": True,
            "secret_free": True,
        },
        "profiles": {
            "personal_profiles": "Selected personal profile supplies applicant, address, IBAN/payment wording, IVA/IRS, travel origin, and personal distances.",
            "service_profiles": "Auto-detected or explicitly selected service profile supplies payment/service-place pattern, recipient, and transport defaults.",
        },
        "paths_are_contractual": False,
        "private_runtime_files_exposed": False,
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
        "- `apply_endpoint_available`: true",
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
        "message": "LegalPDF adapter import plan is ready. No local files were changed. A guarded apply endpoint is available with explicit confirmation.",
        "tasks": tasks,
        "blocking_count": blocking_count,
        "preview": preview,
        "write_allowed": False,
        "send_allowed": False,
        "managed_data_changed": False,
        "apply_endpoint_available": True,
        "apply_endpoint": "/api/integration/apply-import-plan",
        "apply_confirmation_phrase": LEGALPDF_IMPORT_CONFIRMATION_PHRASE,
    }
    plan["plan_markdown"] = legalpdf_adapter_import_plan_markdown(plan)
    return plan


LEGALPDF_IMPORT_CONFIRMATION_PHRASE = "APPLY LEGALPDF IMPORT PLAN"
LEGALPDF_RESTORE_CONFIRMATION_PHRASE = "RESTORE LEGALPDF APPLY BACKUP"
PROFILE_REQUIRED_PRESERVE_PATHS = tuple(PROFILE_DEFAULT_REMOVAL_BLOCK_PREFIXES)


def _nested_exists(value: dict[str, Any], path: str) -> bool:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _nested_get(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        current = current[part]
    return current


def _nested_set(value: dict[str, Any], path: str, replacement: Any) -> None:
    current: Any = value
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(current, dict):
            raise IntakeError(f"Cannot preserve nested import field through non-object path: {path}")
        current = current.setdefault(part, {})
    if not isinstance(current, dict):
        raise IntakeError(f"Cannot preserve nested import field through non-object path: {path}")
    current[parts[-1]] = copy.deepcopy(replacement)


def _preserve_local_profile_defaults(
    *,
    target_key: str,
    current_record: dict[str, Any],
    incoming_record: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    merged = copy.deepcopy(incoming_record)
    preserved: list[str] = []
    for path in PROFILE_REQUIRED_PRESERVE_PATHS:
        if _nested_exists(current_record, path):
            current_value = _nested_get(current_record, path)
            incoming_value = _nested_get(incoming_record, path) if _nested_exists(incoming_record, path) else None
            if stable_json_hash(current_value) != stable_json_hash(incoming_value):
                preserved.append(path)
            _nested_set(merged, path, current_value)
    if not isinstance(merged.get("defaults"), dict):
        raise IntakeError(f"Imported service profile {target_key} is missing defaults.")
    return merged, preserved


def _validate_import_profile_record(profile_key: str, record: dict[str, Any], paths: AppPaths) -> None:
    preview = preview_service_profile(profile_key, record, paths)
    if preview.get("status") != "ready":
        questions = preview.get("question_text") or "missing required profile defaults"
        raise IntakeError(f"Imported service profile {profile_key} is incomplete: {questions}")


def _incoming_profile_records_for_apply(
    payload: dict[str, Any],
    paths: AppPaths,
    plan: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    validation = validate_backup_payload(payload, paths)
    datasets = validation["datasets"]
    incoming_profiles = datasets.get("service_profiles", {})
    if not isinstance(incoming_profiles, dict):
        raise IntakeError("Incoming service_profiles dataset must be a JSON object.")
    current_profiles = load_profiles(paths.service_profiles)
    records: dict[str, dict[str, Any]] = {}
    applied: list[dict[str, Any]] = []

    for task in plan.get("tasks") or []:
        if not isinstance(task, dict) or task.get("category") != "service_profile":
            continue
        action = str(task.get("action") or "")
        if action not in {"create", "review_update"}:
            continue
        source_key = str(task.get("source_key") or "").strip()
        target_key = str(task.get("target_key") or source_key).strip()
        incoming = incoming_profiles.get(source_key)
        if not isinstance(incoming, dict):
            raise IntakeError(f"Incoming service profile is missing or invalid: {source_key}")
        if action == "review_update":
            current = current_profiles.get(target_key)
            if not isinstance(current, dict):
                raise IntakeError(f"Cannot update missing service profile: {target_key}")
            record, preserved_paths = _preserve_local_profile_defaults(
                target_key=target_key,
                current_record=current,
                incoming_record=incoming,
            )
        else:
            record = copy.deepcopy(incoming)
            preserved_paths = []
        _validate_import_profile_record(target_key, record, paths)
        records[target_key] = record
        applied.append({
            "source_key": source_key,
            "target_key": target_key,
            "action": "update" if action == "review_update" else "create",
            "preserved_required_default_paths": preserved_paths,
            "incoming_hash": stable_json_hash(incoming),
            "applied_hash": stable_json_hash(record),
        })
    return records, applied


def _incoming_court_email_records_for_apply(
    payload: dict[str, Any],
    paths: AppPaths,
    plan: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    validation = validate_backup_payload(payload, paths)
    datasets = validation["datasets"]
    incoming_records = datasets.get("court_emails", [])
    if not isinstance(incoming_records, list):
        raise IntakeError("Incoming court_emails dataset must be a JSON list.")
    current_records = read_json_list(paths.court_emails)
    current_by_key = {
        str(record.get("key") or "").strip(): record
        for record in current_records
        if str(record.get("key") or "").strip()
    }
    incoming_by_key = {
        str(record.get("key") or "").strip(): record
        for record in incoming_records
        if isinstance(record, dict) and str(record.get("key") or "").strip()
    }
    records: dict[str, dict[str, Any]] = {}
    applied: list[dict[str, Any]] = []
    for task in plan.get("tasks") or []:
        if not isinstance(task, dict) or task.get("category") != "court_email":
            continue
        action = str(task.get("action") or "")
        if action not in {"create", "review_update"}:
            continue
        key = str(task.get("target_key") or task.get("source_key") or "").strip()
        incoming = incoming_by_key.get(key)
        if not isinstance(incoming, dict):
            raise IntakeError(f"Incoming court email is missing or invalid: {key}")
        normalized = normalize_court_email_record(incoming, current_by_key.get(key))
        records[key] = normalized
        applied.append({
            "key": key,
            "action": "update" if action == "review_update" else "create",
            "incoming_hash": stable_json_hash(incoming),
            "applied_hash": stable_json_hash(normalized),
        })
    return records, applied


def _legalpdf_apply_report_markdown(report: dict[str, Any]) -> str:
    profile_rows = [
        [item.get("target_key", ""), item.get("action", ""), ", ".join(item.get("preserved_required_default_paths") or [])]
        for item in report.get("applied_profiles") or []
    ]
    court_rows = [
        [item.get("key", ""), item.get("action", "")]
        for item in report.get("applied_court_emails") or []
    ]
    lines = [
        "# LegalPDF Adapter Import Apply Report",
        "",
        report.get("message") or "Guarded import applied.",
        "",
        "This report is private runtime output. LegalPDF Translate was not modified. Gmail was not involved.",
        "",
        "## Applied Service Profiles",
        "",
        _markdown_table(["Profile", "Action", "Preserved local required defaults"], profile_rows),
        "",
        "## Applied Court Emails",
        "",
        _markdown_table(["Court email key", "Action"], court_rows),
        "",
        "## Safety",
        "",
        "- `send_allowed`: false",
        "- `legalpdf_write_allowed`: false",
        f"- Pre-apply backup: `{report.get('pre_apply_backup_file', '')}`",
        "",
    ]
    return "\n".join(lines)


def _legalpdf_restore_report_markdown(report: dict[str, Any]) -> str:
    profile_rows = [
        [item.get("target_key", ""), item.get("restore_action", ""), item.get("result", "")]
        for item in report.get("restored_profiles") or []
    ]
    court_rows = [
        [item.get("key", ""), item.get("restore_action", ""), item.get("result", "")]
        for item in report.get("restored_court_emails") or []
    ]
    lines = [
        "# LegalPDF Adapter Import Restore Report",
        "",
        report.get("message") or "Guarded restore applied.",
        "",
        "This report is private runtime output. LegalPDF Translate was not modified. Gmail was not involved.",
        "",
        "## Restored Service Profiles",
        "",
        _markdown_table(["Profile", "Restore action", "Result"], profile_rows),
        "",
        "## Restored Court Emails",
        "",
        _markdown_table(["Court email key", "Restore action", "Result"], court_rows),
        "",
        "## Safety",
        "",
        "- `send_allowed`: false",
        "- `legalpdf_write_allowed`: false",
        f"- Source apply report: `{report.get('source_apply_report_id', '')}`",
        f"- Pre-restore backup: `{report.get('pre_restore_backup_file', '')}`",
        "",
    ]
    return "\n".join(lines)


def apply_legalpdf_adapter_import_plan(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    if not bool(payload.get("confirm_apply")):
        raise IntakeError("LegalPDF import apply requires confirm_apply=true and the exact confirmation phrase.")
    phrase = str(payload.get("confirmation_phrase") or "").strip()
    if phrase != LEGALPDF_IMPORT_CONFIRMATION_PHRASE:
        raise IntakeError(f'LegalPDF import apply requires confirmation phrase "{LEGALPDF_IMPORT_CONFIRMATION_PHRASE}".')
    reason = str(payload.get("apply_reason") or payload.get("reason") or "").strip()
    if len(reason) < 8:
        raise IntakeError("LegalPDF import apply requires a short apply_reason explaining why this import is safe.")

    plan = build_legalpdf_adapter_import_plan(payload, paths)
    if int(plan.get("blocking_count") or 0) > 0:
        return {
            "status": "blocked",
            "message": "LegalPDF import apply is blocked because the adapter plan contains blocking tasks.",
            "blocking_count": plan.get("blocking_count", 0),
            "tasks": plan.get("tasks", []),
            "plan": plan,
            "write_allowed": False,
            "managed_data_changed": False,
            "legalpdf_write_allowed": False,
            "send_allowed": False,
        }

    profile_records, applied_profiles = _incoming_profile_records_for_apply(payload, paths, plan)
    court_records, applied_court_emails = _incoming_court_email_records_for_apply(payload, paths, plan)
    unchanged_tasks = [
        {
            "category": task.get("category", ""),
            "target_key": task.get("target_key", task.get("source_key", "")),
            "action": task.get("action", ""),
        }
        for task in plan.get("tasks") or []
        if isinstance(task, dict) and str(task.get("action") or "") in {"verify_unchanged"}
    ]

    if not profile_records and not court_records:
        return {
            "status": "no_changes",
            "message": "LegalPDF import apply found no create/update tasks to write.",
            "applied_profiles": [],
            "applied_court_emails": [],
            "skipped_tasks": unchanged_tasks,
            "write_allowed": False,
            "managed_data_changed": False,
            "legalpdf_write_allowed": False,
            "send_allowed": False,
        }

    pre_apply_backup = backup_payload(paths)
    pre_apply_backup["reason"] = f"Automatic backup before LegalPDF adapter import apply: {reason}"
    pre_apply_backup_file = write_backup_file(pre_apply_backup, paths, prefix="pre-legalpdf-import-backup")

    current_profiles = load_profiles(paths.service_profiles)
    updated_profiles = copy.deepcopy(current_profiles)
    profile_changes: list[dict[str, Any]] = []
    for item in applied_profiles:
        key = item["target_key"]
        before = copy.deepcopy(current_profiles.get(key)) if key in current_profiles else None
        after = profile_records[key]
        updated_profiles[key] = after
        change = profile_change_payload(
            profile_key=key,
            before=before,
            after=after,
            reason=f"LegalPDF adapter import apply: {reason}",
        )
        if change.get("changes"):
            change["import_source"] = "legalpdf_adapter_import_plan"
            profile_changes.append(change)
    write_json_object(paths.service_profiles, updated_profiles)
    for change in profile_changes:
        append_profile_change_log(change, paths)

    current_courts = read_json_list(paths.court_emails)
    court_by_key = {
        str(record.get("key") or "").strip(): copy.deepcopy(record)
        for record in current_courts
        if str(record.get("key") or "").strip()
    }
    for key, record in court_records.items():
        court_by_key[key] = record
    ordered_existing_keys = [str(record.get("key") or "").strip() for record in current_courts if str(record.get("key") or "").strip()]
    new_keys = sorted(key for key in court_records if key not in ordered_existing_keys)
    ordered_keys = ordered_existing_keys + new_keys
    write_json_list(paths.court_emails, [court_by_key[key] for key in ordered_keys])

    report = {
        "kind": "legalpdf_adapter_import_apply_report",
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "applied",
        "message": "LegalPDF adapter import applied to local Honorários reference data. LegalPDF Translate was not modified.",
        "apply_reason": reason,
        "applied_profiles": applied_profiles,
        "applied_court_emails": applied_court_emails,
        "skipped_tasks": unchanged_tasks,
        "profile_change_ids": [change.get("change_id") for change in profile_changes],
        "pre_apply_backup_file": str(pre_apply_backup_file),
        "plan": plan,
        "write_allowed": True,
        "managed_data_changed": True,
        "legalpdf_write_allowed": False,
        "send_allowed": False,
    }
    paths.integration_report_output_dir.mkdir(parents=True, exist_ok=True)
    report_id = f"legalpdf-import-apply-{timestamp_slug()}-{secrets.token_hex(4)}"
    report_json_file = paths.integration_report_output_dir / f"{report_id}.json"
    report_md_file = paths.integration_report_output_dir / f"{report_id}.md"
    report_json_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_md_file.write_text(_legalpdf_apply_report_markdown(report), encoding="utf-8")
    return {
        **report,
        "apply_report_json_file": str(report_json_file),
        "apply_report_markdown_file": str(report_md_file),
        "backup_status": backup_status_payload(paths),
    }


def _safe_apply_report_summary(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("kind") != "legalpdf_adapter_import_apply_report":
        return None

    applied_profiles = [
        {
            "source_key": str(item.get("source_key") or ""),
            "target_key": str(item.get("target_key") or ""),
            "action": str(item.get("action") or ""),
            "preserved_required_default_paths": [
                str(value)
                for value in (item.get("preserved_required_default_paths") or [])
                if str(value or "").strip()
            ],
        }
        for item in (data.get("applied_profiles") or [])
        if isinstance(item, dict)
    ]
    applied_court_emails = [
        {
            "key": str(item.get("key") or ""),
            "action": str(item.get("action") or ""),
        }
        for item in (data.get("applied_court_emails") or [])
        if isinstance(item, dict)
    ]
    markdown_path = path.with_suffix(".md")
    return {
        "report_id": path.stem,
        "status": str(data.get("status") or ""),
        "created_at": str(data.get("created_at") or ""),
        "message": str(data.get("message") or ""),
        "apply_reason": str(data.get("apply_reason") or ""),
        "report_json_file": str(path),
        "report_markdown_file": str(markdown_path) if markdown_path.exists() else "",
        "pre_apply_backup_file": str(data.get("pre_apply_backup_file") or ""),
        "profile_change_ids": [
            str(value)
            for value in (data.get("profile_change_ids") or [])
            if str(value or "").strip()
        ],
        "applied_profile_count": len(applied_profiles),
        "applied_court_email_count": len(applied_court_emails),
        "applied_profiles": applied_profiles,
        "applied_court_emails": applied_court_emails,
        "legalpdf_write_allowed": False,
        "send_allowed": False,
    }


def _resolve_legalpdf_apply_report_path(paths: AppPaths, report_id: str) -> Path:
    value = str(report_id or "").strip()
    if value.endswith(".json"):
        value = value[:-5]
    if not LEGALPDF_APPLY_REPORT_ID_RE.fullmatch(value):
        raise IntakeError("LegalPDF apply report id is invalid.")
    root = paths.integration_report_output_dir.resolve()
    path = (root / f"{value}.json").resolve()
    if path.parent != root:
        raise IntakeError("LegalPDF apply report id is invalid.")
    if not path.exists() or not path.is_file():
        raise IntakeError("LegalPDF apply report was not found.")
    return path


def _safe_pre_apply_backup_datasets(report: dict[str, Any], paths: AppPaths) -> tuple[bool, dict[str, Any]]:
    raw_path = str(report.get("pre_apply_backup_file") or "").strip()
    if not raw_path:
        return False, {}
    backup_path = Path(raw_path)
    try:
        backup_root = paths.backup_output_dir.resolve()
        resolved = backup_path.resolve()
    except OSError:
        return False, {}
    if resolved.parent != backup_root or resolved.suffix.casefold() != ".json":
        return False, {}
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, {}
    if not isinstance(data, dict) or data.get("kind") != BACKUP_KIND:
        return False, {}
    datasets = data.get("datasets")
    if not isinstance(datasets, dict):
        return False, {}
    return True, datasets


def _current_hash_status(current_record: Any, applied_hash: str) -> dict[str, Any]:
    if current_record is None:
        return {
            "current_hash": "",
            "current_matches_applied": False,
            "changed_since_apply": bool(applied_hash),
            "current_status": "missing",
        }
    current_hash = stable_json_hash(current_record)
    matches = bool(applied_hash) and current_hash == applied_hash
    if matches:
        status = "matches_applied"
    elif applied_hash:
        status = "changed_after_apply"
    else:
        status = "present_without_applied_hash"
    return {
        "current_hash": current_hash,
        "current_matches_applied": matches,
        "changed_since_apply": bool(applied_hash) and not matches,
        "current_status": status,
    }


def _restore_hash_status(
    current_record: Any,
    *,
    backup_available: bool,
    backup_record: Any,
    applied_action: str,
) -> dict[str, Any]:
    current_hash = stable_json_hash(current_record) if current_record is not None else ""
    current_record_status = "present" if current_record is not None else "missing"
    if not backup_available:
        return {
            "restore_action": "blocked",
            "backup_record_status": "unavailable",
            "pre_apply_hash": "",
            "current_hash": current_hash,
            "current_record_status": current_record_status,
            "current_matches_pre_apply": False,
            "would_change_current": False,
            "blockers": ["Pre-apply backup is unavailable."],
        }

    normalized_action = str(applied_action or "").strip().casefold()
    if backup_record is None:
        if normalized_action == "create":
            current_matches_pre_apply = current_record is None
            return {
                "restore_action": "remove_created_record",
                "backup_record_status": "missing_before_apply",
                "pre_apply_hash": "",
                "current_hash": current_hash,
                "current_record_status": current_record_status,
                "current_matches_pre_apply": current_matches_pre_apply,
                "would_change_current": not current_matches_pre_apply,
                "blockers": [],
            }
        return {
            "restore_action": "blocked",
            "backup_record_status": "missing",
            "pre_apply_hash": "",
            "current_hash": current_hash,
            "current_record_status": current_record_status,
            "current_matches_pre_apply": False,
            "would_change_current": False,
            "blockers": ["Pre-apply backup does not contain this record."],
        }

    pre_apply_hash = stable_json_hash(backup_record)
    current_matches_pre_apply = bool(current_hash) and current_hash == pre_apply_hash
    return {
        "restore_action": "restore_pre_apply_record",
        "backup_record_status": "present",
        "pre_apply_hash": pre_apply_hash,
        "current_hash": current_hash,
        "current_record_status": current_record_status,
        "current_matches_pre_apply": current_matches_pre_apply,
        "would_change_current": not current_matches_pre_apply,
        "blockers": [],
    }


def legalpdf_apply_restore_plan(paths: AppPaths, *, report_id: str) -> dict[str, Any]:
    path = _resolve_legalpdf_apply_report_path(paths, report_id)
    try:
        report_data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError("LegalPDF apply report could not be read.") from exc
    summary = _safe_apply_report_summary(path)
    if summary is None:
        raise IntakeError("LegalPDF apply report is not an apply report.")

    backup_available, backup_datasets = _safe_pre_apply_backup_datasets(report_data, paths)
    backup_profiles = backup_datasets.get("service_profiles") if isinstance(backup_datasets.get("service_profiles"), dict) else {}
    backup_courts = backup_datasets.get("court_emails") if isinstance(backup_datasets.get("court_emails"), list) else []
    backup_courts_by_key = {
        str(record.get("key") or "").strip(): record
        for record in backup_courts
        if isinstance(record, dict) and str(record.get("key") or "").strip()
    }
    current_profiles = load_profiles(paths.service_profiles)
    current_courts = read_json_list(paths.court_emails)
    current_courts_by_key = {
        str(record.get("key") or "").strip(): record
        for record in current_courts
        if str(record.get("key") or "").strip()
    }

    profile_rows: list[dict[str, Any]] = []
    for item in report_data.get("applied_profiles") or []:
        if not isinstance(item, dict):
            continue
        target_key = str(item.get("target_key") or "").strip()
        if not target_key:
            continue
        backup_record = backup_profiles.get(target_key) if isinstance(backup_profiles, dict) else None
        applied_action = str(item.get("action") or "").strip()
        row = {
            "source_key": str(item.get("source_key") or "").strip(),
            "target_key": target_key,
            "applied_action": applied_action,
            "applied_hash": str(item.get("applied_hash") or "").strip(),
            "preserved_required_default_paths": [
                str(value)
                for value in (item.get("preserved_required_default_paths") or [])
                if str(value or "").strip()
            ],
        }
        row.update(
            _restore_hash_status(
                current_profiles.get(target_key),
                backup_available=backup_available,
                backup_record=backup_record,
                applied_action=applied_action,
            )
        )
        profile_rows.append(row)

    court_rows: list[dict[str, Any]] = []
    for item in report_data.get("applied_court_emails") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        applied_action = str(item.get("action") or "").strip()
        row = {
            "key": key,
            "applied_action": applied_action,
            "applied_hash": str(item.get("applied_hash") or "").strip(),
        }
        row.update(
            _restore_hash_status(
                current_courts_by_key.get(key),
                backup_available=backup_available,
                backup_record=backup_courts_by_key.get(key),
                applied_action=applied_action,
            )
        )
        court_rows.append(row)

    blocking_count = sum(1 for row in [*profile_rows, *court_rows] if row.get("blockers"))
    status = "ready" if not blocking_count else "blocked"
    message = (
        "LegalPDF restore plan loaded. This is read-only; no restore was performed."
        if status == "ready"
        else "LegalPDF restore plan found blockers. This is read-only; no restore was performed."
    )
    return {
        "status": status,
        "message": message,
        "report": summary,
        "backup_available": backup_available,
        "restore_allowed": False,
        "blocking_count": blocking_count,
        "restore_plan": {
            "profile_count": len(profile_rows),
            "court_email_count": len(court_rows),
            "profiles": profile_rows,
            "court_emails": court_rows,
        },
        "write_allowed": False,
        "managed_data_changed": False,
        "legalpdf_write_allowed": False,
        "send_allowed": False,
    }


def _legalpdf_restore_blocked(message: str, *, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "blocked",
        "message": message,
        "restore_allowed": False,
        "write_allowed": False,
        "managed_data_changed": False,
        "legalpdf_write_allowed": False,
        "send_allowed": False,
    }
    if plan is not None:
        result["restore_plan"] = plan.get("restore_plan", {})
        result["blocking_count"] = plan.get("blocking_count", 0)
        result["report"] = plan.get("report", {})
    return result


def _backup_court_emails_by_key(datasets: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    records = datasets.get("court_emails") if isinstance(datasets.get("court_emails"), list) else []
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        key = str(record.get("key") or "").strip()
        if not key:
            continue
        by_key[key] = copy.deepcopy(record)
        if key not in order:
            order.append(key)
    return by_key, order


def _restore_report_row(row: dict[str, Any], *, key_field: str) -> dict[str, Any]:
    key = str(row.get(key_field) or "").strip()
    return {
        key_field: key,
        "applied_action": str(row.get("applied_action") or ""),
        "restore_action": str(row.get("restore_action") or ""),
        "result": "changed" if row.get("would_change_current") else "unchanged",
        "pre_apply_hash": str(row.get("pre_apply_hash") or ""),
        "previous_current_hash": str(row.get("current_hash") or ""),
    }


def apply_legalpdf_restore(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    if not bool(payload.get("confirm_restore")):
        raise IntakeError("LegalPDF apply restore requires confirm_restore=true and the exact confirmation phrase.")
    phrase = str(payload.get("confirmation_phrase") or "").strip()
    if phrase != LEGALPDF_RESTORE_CONFIRMATION_PHRASE:
        raise IntakeError(f'LegalPDF apply restore requires confirmation phrase "{LEGALPDF_RESTORE_CONFIRMATION_PHRASE}".')
    reason = str(payload.get("restore_reason") or payload.get("reason") or "").strip()
    if len(reason) < 8:
        raise IntakeError("LegalPDF apply restore requires a short restore_reason explaining why this rollback is safe.")
    report_id = str(payload.get("report_id") or "").strip()
    if not report_id:
        raise IntakeError("LegalPDF apply restore requires report_id.")

    plan = legalpdf_apply_restore_plan(paths, report_id=report_id)
    if plan.get("status") != "ready" or int(plan.get("blocking_count") or 0) > 0:
        return _legalpdf_restore_blocked(
            "LegalPDF apply restore is blocked because the restore plan contains blockers.",
            plan=plan,
        )

    path = _resolve_legalpdf_apply_report_path(paths, report_id)
    try:
        report_data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError("LegalPDF apply report could not be read.") from exc
    backup_available, backup_datasets = _safe_pre_apply_backup_datasets(report_data, paths)
    if not backup_available:
        return _legalpdf_restore_blocked(
            "LegalPDF apply restore is blocked because the pre-apply backup is unavailable.",
            plan=plan,
        )

    backup_profiles = backup_datasets.get("service_profiles") if isinstance(backup_datasets.get("service_profiles"), dict) else {}
    backup_courts_by_key, backup_court_order = _backup_court_emails_by_key(backup_datasets)

    current_profiles = load_profiles(paths.service_profiles)
    updated_profiles = copy.deepcopy(current_profiles)
    profile_changes: list[dict[str, Any]] = []
    restored_profiles: list[dict[str, Any]] = []
    for row in plan.get("restore_plan", {}).get("profiles", []):
        if not isinstance(row, dict):
            continue
        target_key = str(row.get("target_key") or "").strip()
        restore_action = str(row.get("restore_action") or "").strip()
        if not target_key or restore_action not in {"restore_pre_apply_record", "remove_created_record"}:
            continue
        before = copy.deepcopy(current_profiles.get(target_key)) if target_key in current_profiles else None
        if restore_action == "restore_pre_apply_record":
            backup_record = backup_profiles.get(target_key) if isinstance(backup_profiles, dict) else None
            if not isinstance(backup_record, dict):
                return _legalpdf_restore_blocked(
                    f"LegalPDF apply restore is blocked because the pre-apply profile is missing: {target_key}",
                    plan=plan,
                )
            after = copy.deepcopy(backup_record)
            updated_profiles[target_key] = after
        else:
            after = None
            updated_profiles.pop(target_key, None)

        summary = _restore_report_row(row, key_field="target_key")
        if stable_json_hash(before) != stable_json_hash(after):
            change = profile_change_payload(
                profile_key=target_key,
                before=before,
                after=after,
                reason=f"LegalPDF apply restore: {reason}",
            )
            change["restore_source"] = "legalpdf_apply_restore"
            change["restore_of_report"] = path.stem
            change["restore_action"] = restore_action
            profile_changes.append(change)
            summary["profile_change_id"] = change.get("change_id", "")
        restored_profiles.append(summary)

    current_courts = read_json_list(paths.court_emails)
    current_court_by_key = {
        str(record.get("key") or "").strip(): copy.deepcopy(record)
        for record in current_courts
        if isinstance(record, dict) and str(record.get("key") or "").strip()
    }
    updated_court_by_key = copy.deepcopy(current_court_by_key)
    restored_court_emails: list[dict[str, Any]] = []
    changed_court_keys: set[str] = set()
    for row in plan.get("restore_plan", {}).get("court_emails", []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        restore_action = str(row.get("restore_action") or "").strip()
        if not key or restore_action not in {"restore_pre_apply_record", "remove_created_record"}:
            continue
        before = copy.deepcopy(current_court_by_key.get(key))
        if restore_action == "restore_pre_apply_record":
            backup_record = backup_courts_by_key.get(key)
            if not isinstance(backup_record, dict):
                return _legalpdf_restore_blocked(
                    f"LegalPDF apply restore is blocked because the pre-apply court email is missing: {key}",
                    plan=plan,
                )
            after = copy.deepcopy(backup_record)
            updated_court_by_key[key] = after
        else:
            after = None
            updated_court_by_key.pop(key, None)
        summary = _restore_report_row(row, key_field="key")
        if stable_json_hash(before) != stable_json_hash(after):
            changed_court_keys.add(key)
        restored_court_emails.append(summary)

    if not profile_changes and not changed_court_keys:
        return {
            "status": "no_changes",
            "message": "LegalPDF apply restore found no local reference changes to write.",
            "report": plan.get("report", {}),
            "restored_profiles": restored_profiles,
            "restored_court_emails": restored_court_emails,
            "restore_allowed": True,
            "write_allowed": False,
            "managed_data_changed": False,
            "legalpdf_write_allowed": False,
            "send_allowed": False,
        }

    pre_restore_backup = backup_payload(paths)
    pre_restore_backup["reason"] = f"Automatic backup before LegalPDF apply restore: {reason}"
    pre_restore_backup_file = write_backup_file(pre_restore_backup, paths, prefix="pre-legalpdf-restore-backup")

    write_json_object(paths.service_profiles, updated_profiles)
    for change in profile_changes:
        append_profile_change_log(change, paths)

    current_order = [str(record.get("key") or "").strip() for record in current_courts if isinstance(record, dict) and str(record.get("key") or "").strip()]
    ordered_keys: list[str] = []
    for key in [*current_order, *backup_court_order, *sorted(updated_court_by_key)]:
        if key in updated_court_by_key and key not in ordered_keys:
            ordered_keys.append(key)
    write_json_list(paths.court_emails, [updated_court_by_key[key] for key in ordered_keys])

    report = {
        "kind": "legalpdf_adapter_import_restore_report",
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "restored",
        "message": "LegalPDF apply restore was applied to local Honorários reference data. LegalPDF Translate was not modified.",
        "restore_reason": reason,
        "source_apply_report_id": path.stem,
        "restored_profiles": restored_profiles,
        "restored_court_emails": restored_court_emails,
        "pre_restore_backup_file": str(pre_restore_backup_file),
        "restore_allowed": True,
        "write_allowed": True,
        "managed_data_changed": True,
        "legalpdf_write_allowed": False,
        "send_allowed": False,
    }
    paths.integration_report_output_dir.mkdir(parents=True, exist_ok=True)
    restore_report_id = f"legalpdf-import-restore-{timestamp_slug()}-{secrets.token_hex(4)}"
    restore_report_json_file = paths.integration_report_output_dir / f"{restore_report_id}.json"
    restore_report_md_file = paths.integration_report_output_dir / f"{restore_report_id}.md"
    restore_report_json_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    restore_report_md_file.write_text(_legalpdf_restore_report_markdown(report), encoding="utf-8")
    return {
        **report,
        "restore_report_json_file": str(restore_report_json_file),
        "restore_report_markdown_file": str(restore_report_md_file),
        "backup_status": backup_status_payload(paths),
    }


def legalpdf_apply_report_detail(paths: AppPaths, *, report_id: str) -> dict[str, Any]:
    path = _resolve_legalpdf_apply_report_path(paths, report_id)
    try:
        report_data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError("LegalPDF apply report could not be read.") from exc
    summary = _safe_apply_report_summary(path)
    if summary is None:
        raise IntakeError("LegalPDF apply report is not an apply report.")

    backup_available, backup_datasets = _safe_pre_apply_backup_datasets(report_data, paths)
    backup_profiles = backup_datasets.get("service_profiles") if isinstance(backup_datasets.get("service_profiles"), dict) else {}
    backup_courts = backup_datasets.get("court_emails") if isinstance(backup_datasets.get("court_emails"), list) else []
    backup_courts_by_key = {
        str(record.get("key") or "").strip(): record
        for record in backup_courts
        if isinstance(record, dict) and str(record.get("key") or "").strip()
    }
    current_profiles = load_profiles(paths.service_profiles)
    current_courts = read_json_list(paths.court_emails)
    current_courts_by_key = {
        str(record.get("key") or "").strip(): record
        for record in current_courts
        if str(record.get("key") or "").strip()
    }

    profile_rows: list[dict[str, Any]] = []
    for item in report_data.get("applied_profiles") or []:
        if not isinstance(item, dict):
            continue
        target_key = str(item.get("target_key") or "").strip()
        applied_hash = str(item.get("applied_hash") or "").strip()
        row = {
            "source_key": str(item.get("source_key") or "").strip(),
            "target_key": target_key,
            "action": str(item.get("action") or "").strip(),
            "incoming_hash": str(item.get("incoming_hash") or "").strip(),
            "applied_hash": applied_hash,
            "preserved_required_default_paths": [
                str(value)
                for value in (item.get("preserved_required_default_paths") or [])
                if str(value or "").strip()
            ],
            "pre_apply_hash": stable_json_hash(backup_profiles[target_key])
            if backup_available and isinstance(backup_profiles, dict) and target_key in backup_profiles
            else "",
            "pre_apply_status": "present"
            if backup_available and isinstance(backup_profiles, dict) and target_key in backup_profiles
            else ("missing" if backup_available else "unavailable"),
        }
        row.update(_current_hash_status(current_profiles.get(target_key), applied_hash))
        profile_rows.append(row)

    court_rows: list[dict[str, Any]] = []
    for item in report_data.get("applied_court_emails") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        applied_hash = str(item.get("applied_hash") or "").strip()
        row = {
            "key": key,
            "action": str(item.get("action") or "").strip(),
            "incoming_hash": str(item.get("incoming_hash") or "").strip(),
            "applied_hash": applied_hash,
            "pre_apply_hash": stable_json_hash(backup_courts_by_key[key])
            if backup_available and key in backup_courts_by_key
            else "",
            "pre_apply_status": "present" if backup_available and key in backup_courts_by_key else ("missing" if backup_available else "unavailable"),
        }
        row.update(_current_hash_status(current_courts_by_key.get(key), applied_hash))
        court_rows.append(row)

    return {
        "status": "ready",
        "message": "LegalPDF apply report detail loaded. This is a read-only redacted comparison.",
        "report": summary,
        "backup_available": backup_available,
        "comparison": {
            "profile_count": len(profile_rows),
            "court_email_count": len(court_rows),
            "profiles": profile_rows,
            "court_emails": court_rows,
        },
        "write_allowed": False,
        "managed_data_changed": False,
        "legalpdf_write_allowed": False,
        "send_allowed": False,
    }


def legalpdf_apply_history(paths: AppPaths, *, limit: int = 20) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    if paths.integration_report_output_dir.exists():
        for path in paths.integration_report_output_dir.glob("legalpdf-import-apply-*.json"):
            if not path.is_file():
                continue
            summary = _safe_apply_report_summary(path)
            if summary is not None:
                reports.append(summary)
    reports.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("report_json_file") or "")), reverse=True)
    limited = reports[: max(1, int(limit))]
    return {
        "status": "ready",
        "message": "LegalPDF apply history loaded. This endpoint is read-only and returns summaries only.",
        "reports": limited,
        "report_count": len(reports),
        "returned_count": len(limited),
        "write_allowed": False,
        "managed_data_changed": False,
        "legalpdf_write_allowed": False,
        "send_allowed": False,
    }


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
    phrase = str(payload.get("confirmation_phrase") or "").strip()
    if phrase != LOCAL_BACKUP_RESTORE_PHRASE:
        raise IntakeError(f"Backup restore requires the exact confirmation phrase: {LOCAL_BACKUP_RESTORE_PHRASE}")
    restore_reason = str(payload.get("restore_reason") or "").strip()
    if not restore_reason:
        raise IntakeError("Backup restore requires a short restore_reason explaining why this rollback is safe.")
    validation = validate_backup_payload(payload, paths)
    pre_restore_backup = backup_payload(paths)
    pre_restore_backup["reason"] = f"Automatic backup before local restore. Restore reason: {restore_reason}"
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
        "restore_reason": restore_reason,
        "backup_status": backup_status_payload(paths),
        "send_allowed": False,
    }


def stable_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


PREPARED_REVIEW_VERSION = "2026-05-09.prepared-review.v1"
_PREPARED_REVIEW_SECRET = secrets.token_bytes(32)


def _signed_review_token(kind: str, fingerprint: str, manifest: str = "") -> str:
    message = f"{PREPARED_REVIEW_VERSION}|{kind}|{fingerprint}|{manifest}".encode("utf-8")
    return hmac.new(_PREPARED_REVIEW_SECRET, message, hashlib.sha256).hexdigest()


def _resolve_optional_path(raw_path: Any) -> Path:
    path = Path(str(raw_path or "").strip())
    if not str(path):
        raise IntakeError("Current prepared review is required before using this prepared payload.")
    resolved = path if path.is_absolute() else ROOT / path
    return resolved.resolve()


def _intake_identity_payload(intake: dict[str, Any]) -> dict[str, str]:
    case_number, service_date, period = request_identity_key({
        "case_number": str(intake.get("case_number") or ""),
        "service_date": get_service_date_value(intake),
        "service_period_label": str(intake.get("service_period_label") or "").strip(),
    })
    return {
        "case_number": case_number,
        "service_date": service_date,
        "service_period_label": period,
        "service_start_time": str(intake.get("service_start_time") or "").strip(),
        "service_end_time": str(intake.get("service_end_time") or "").strip(),
    }


def _prepared_file_sha256(path: Path, label: str) -> str:
    if not path.exists() or not path.is_file():
        raise IntakeError(f"Prepared review {label} file is missing: {path}")
    return file_sha256(path)


def _target_payload_summary(target: dict[str, Any]) -> dict[str, Any]:
    args = target.get("gmail_create_draft_args") if isinstance(target.get("gmail_create_draft_args"), dict) else {}
    attachment_files = args.get("attachment_files") if isinstance(args.get("attachment_files"), list) else target.get("attachment_files", [])
    draft_payload = _resolve_optional_path(target.get("draft_payload"))
    pdf_path = _resolve_optional_path(target.get("pdf"))
    resolved_attachments = [_resolve_optional_path(item) for item in attachment_files]
    return {
        "draft_payload": str(draft_payload),
        "draft_payload_sha256": _prepared_file_sha256(draft_payload, "draft payload"),
        "pdf": str(pdf_path),
        "pdf_sha256": _prepared_file_sha256(pdf_path, "PDF"),
        "attachment_files": [str(item) for item in resolved_attachments],
        "attachment_sha256": {str(item): _prepared_file_sha256(item, "attachment") for item in resolved_attachments},
        "recipient": str(target.get("recipient") or target.get("to") or args.get("to") or "").strip(),
        "subject": str(target.get("subject") or args.get("subject") or "").strip(),
        "request_identity": {
            "case_number": str(target.get("case_number") or "").strip(),
            "service_date": str(target.get("service_date") or "").strip(),
            "service_period_label": str(target.get("service_period_label") or "").strip(),
        },
        "packet_mode": bool(target.get("packet_mode")),
        "underlying_requests": list(target.get("underlying_requests") or []),
        "email_grouping": str(target.get("email_grouping") or "individual"),
        "group_id": str(target.get("group_id") or ""),
        "source_sha256": str(target.get("source_sha256") or ""),
        "personal_profile_id": str(target.get("personal_profile_id") or ""),
        "member_indices": list(target.get("member_indices") or []),
        "child_payload_sha256": {str(_resolve_optional_path(item)): _prepared_file_sha256(_resolve_optional_path(item), "child draft payload")
                                 for item in target.get("child_payload_paths") or []},
    }


def _preflight_review_material(
    *,
    effective_intakes: list[dict[str, Any]],
    recipients: list[dict[str, str]],
    packet_mode: bool,
    correction_mode: bool,
    correction_reason: str,
    email_grouping: str = "individual",
) -> dict[str, Any]:
    return {
        "version": PREPARED_REVIEW_VERSION,
        "kind": "preflight",
        "effective_intakes": effective_intakes,
        "request_identities": [_intake_identity_payload(intake) for intake in effective_intakes],
        "recipients": recipients,
        "packet_mode": bool(packet_mode),
        "correction_mode": bool(correction_mode),
        "correction_reason": str(correction_reason or "").strip(),
        "email_grouping": normalize_email_grouping(email_grouping),
        "email_groups": source_email_group_plan(effective_intakes, recipients) if email_grouping == "source" and not packet_mode else [],
    }


def _preflight_review_from_material(material: dict[str, Any]) -> dict[str, Any]:
    fingerprint = stable_json_hash(material)
    return {
        "version": PREPARED_REVIEW_VERSION,
        "kind": "preflight",
        "review_fingerprint": fingerprint,
        "preflight_review_token": _signed_review_token("preflight", fingerprint),
        "request_count": len(material.get("effective_intakes") or []),
        "packet_mode": bool(material.get("packet_mode")),
        "email_grouping": str(material.get("email_grouping") or "individual"),
        "correction_mode": bool(material.get("correction_mode")),
        "send_allowed": False,
        "write_allowed": False,
    }


def _build_preflight_review(
    *,
    effective_intakes: list[dict[str, Any]],
    recipients: list[dict[str, str]],
    packet_mode: bool,
    correction_mode: bool,
    correction_reason: str,
    email_grouping: str = "individual",
) -> dict[str, Any]:
    material = _preflight_review_material(
        effective_intakes=effective_intakes,
        recipients=recipients,
        packet_mode=packet_mode,
        correction_mode=correction_mode,
        correction_reason=correction_reason,
        email_grouping=email_grouping,
    )
    return _preflight_review_from_material(material)


def _extract_preflight_review_request(payload: dict[str, Any]) -> dict[str, str]:
    nested = payload.get("preflight_review") if isinstance(payload.get("preflight_review"), dict) else {}
    return {
        "review_fingerprint": str(
            payload.get("preflight_fingerprint")
            or payload.get("review_fingerprint")
            or nested.get("review_fingerprint")
            or ""
        ).strip(),
        "preflight_review_token": str(
            payload.get("preflight_review_token")
            or nested.get("preflight_review_token")
            or ""
        ).strip(),
    }


def require_current_preflight_review(
    request_payload: dict[str, Any],
    intakes: list[dict[str, Any]],
    paths: AppPaths,
    *,
    packet_mode: bool,
    correction_reason: str = "",
    email_grouping: str = "individual",
) -> dict[str, Any]:
    requested = _extract_preflight_review_request(request_payload)
    if not requested["review_fingerprint"] or not requested["preflight_review_token"]:
        raise IntakeError("Run a current ready preflight before preparing artifacts.")

    effective_records = [effective_intake_for_profile(intake, paths) for intake in intakes]
    effective_intakes = [record[0] for record in effective_records]
    email_config = load_json(paths.email_config)
    court_directory = read_json_list(paths.court_emails)
    recipients = []
    for intake in effective_intakes:
        recipient, recipient_source = resolve_recipient(intake, email_config, court_directory)
        recipients.append({"recipient": recipient, "recipient_source": recipient_source})
    current = _build_preflight_review(
        effective_intakes=effective_intakes,
        recipients=recipients,
        packet_mode=packet_mode,
        correction_mode=bool(str(correction_reason or "").strip()),
        correction_reason=correction_reason,
        email_grouping=email_grouping,
    )
    if not hmac.compare_digest(requested["review_fingerprint"], current["review_fingerprint"]):
        raise IntakeError("Preflight is stale for the current request snapshot. Run preflight again before preparing artifacts.")
    if not hmac.compare_digest(requested["preflight_review_token"], current["preflight_review_token"]):
        raise IntakeError("Preflight token is stale. Run preflight again before preparing artifacts.")
    return current


def _prepared_review_material(
    *,
    effective_intakes: list[dict[str, Any]],
    items: list[dict[str, Any]],
    packet: dict[str, Any] | None,
    manifest_path: Path,
    packet_mode: bool,
    correction_mode: bool,
    correction_reason: str,
    email_grouping: str = "individual",
    email_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    targets = [packet] if packet else (email_groups if email_grouping == "source" else items)
    target_summaries = [_target_payload_summary(target) for target in targets if isinstance(target, dict)]
    return {
        "version": PREPARED_REVIEW_VERSION,
        "kind": "prepared",
        "manifest": str(manifest_path.resolve()),
        "effective_intakes": effective_intakes,
        "request_identities": [_intake_identity_payload(intake) for intake in effective_intakes],
        "packet_mode": bool(packet_mode),
        "email_grouping": normalize_email_grouping(email_grouping),
        "correction_mode": bool(correction_mode),
        "correction_reason": str(correction_reason or "").strip(),
        "targets": target_summaries,
        "item_payloads": [_target_payload_summary(item) for item in items],
    }


def _prepared_review_from_material(material: dict[str, Any]) -> dict[str, Any]:
    manifest = str(material.get("manifest") or "")
    targets = material.get("targets") if isinstance(material.get("targets"), list) else []
    fingerprint = stable_json_hash(material)
    return {
        "version": PREPARED_REVIEW_VERSION,
        "kind": "prepared",
        "manifest": manifest,
        "review_fingerprint": fingerprint,
        "prepared_review_token": _signed_review_token("prepared", fingerprint, manifest),
        "payload_paths": [str(target.get("draft_payload") or "") for target in targets],
        "pdf_paths": [str(target.get("pdf") or "") for target in targets],
        "request_count": len(material.get("effective_intakes") or []),
        "packet_mode": bool(material.get("packet_mode")),
        "email_grouping": str(material.get("email_grouping") or "individual"),
        "correction_mode": bool(material.get("correction_mode")),
        "correction_reason": str(material.get("correction_reason") or "").strip(),
        "send_allowed": False,
    }


def _extract_prepared_review_request(payload: dict[str, Any]) -> dict[str, str]:
    nested = payload.get("prepared_review") if isinstance(payload.get("prepared_review"), dict) else {}
    return {
        "manifest": str(payload.get("prepared_manifest") or nested.get("manifest") or "").strip(),
        "review_fingerprint": str(payload.get("review_fingerprint") or nested.get("review_fingerprint") or "").strip(),
        "prepared_review_token": str(payload.get("prepared_review_token") or nested.get("prepared_review_token") or "").strip(),
    }


def require_current_prepared_review(payload: dict[str, Any], payload_path: str | Path, paths: AppPaths) -> dict[str, Any]:
    requested = _extract_prepared_review_request(payload)
    if not requested["manifest"] or not requested["review_fingerprint"] or not requested["prepared_review_token"]:
        raise IntakeError("Current prepared review is required before using this prepared payload. Prepare the PDF again from the reviewed request.")

    manifest_path = _resolve_optional_path(requested["manifest"])
    if not manifest_path.exists() or not manifest_path.is_file():
        raise IntakeError("Prepared review manifest is stale or missing. Prepare the PDF again from the reviewed request.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntakeError("Prepared review manifest is invalid. Prepare the PDF again from the reviewed request.") from exc
    if not isinstance(manifest, dict):
        raise IntakeError("Prepared review manifest is invalid. Prepare the PDF again from the reviewed request.")

    review = manifest.get("prepared_review") if isinstance(manifest.get("prepared_review"), dict) else {}
    material = manifest.get("prepared_review_material") if isinstance(manifest.get("prepared_review_material"), dict) else {}
    if not review or not material:
        raise IntakeError("Prepared review manifest does not include prepared review data. Prepare the PDF again from the reviewed request.")

    current_fingerprint = stable_json_hash(material)
    current_token = _signed_review_token("prepared", current_fingerprint, str(manifest_path.resolve()))
    if not hmac.compare_digest(str(review.get("review_fingerprint") or ""), current_fingerprint):
        raise IntakeError("Prepared review manifest is stale. Prepare the PDF again from the reviewed request.")
    if not hmac.compare_digest(requested["review_fingerprint"], current_fingerprint):
        raise IntakeError("Prepared review is stale for this payload. Prepare the PDF again from the reviewed request.")
    if not hmac.compare_digest(str(review.get("prepared_review_token") or ""), current_token):
        raise IntakeError("Prepared review token is stale. Prepare the PDF again from the reviewed request.")
    if not hmac.compare_digest(requested["prepared_review_token"], current_token):
        raise IntakeError("Prepared review token is stale. Prepare the PDF again from the reviewed request.")

    payload_absolute = str(_resolve_optional_path(payload_path))
    payload_paths = [str(item) for item in review.get("payload_paths") or []]
    if payload_absolute not in payload_paths:
        raise IntakeError("Prepared review does not match this draft payload. Prepare the PDF again from the reviewed request.")

    expected_targets = [target for target in material.get("targets") or [] if isinstance(target, dict)]
    target_summary = next((target for target in expected_targets if str(target.get("draft_payload") or "") == payload_absolute), None)
    if not target_summary:
        raise IntakeError("Prepared review does not include this draft payload. Prepare the PDF again from the reviewed request.")
    expected_payload_hash = str(target_summary.get("draft_payload_sha256") or "")
    if not expected_payload_hash:
        raise IntakeError("Prepared review is missing draft payload content evidence. Prepare the PDF again from the reviewed request.")
    if not hmac.compare_digest(_prepared_file_sha256(Path(payload_absolute), "draft payload"), expected_payload_hash):
        raise IntakeError("Prepared draft payload changed after review. Prepare the PDF again from the reviewed request.")

    for raw_child, expected_hash in (target_summary.get("child_payload_sha256") or {}).items():
        if not hmac.compare_digest(_prepared_file_sha256(Path(raw_child), "child draft payload"), str(expected_hash)):
            raise IntakeError("Prepared child draft payload changed after review. Prepare the group again from the reviewed requests.")

    expected_attachment_hashes = target_summary.get("attachment_sha256") if isinstance(target_summary.get("attachment_sha256"), dict) else {}
    for raw_attachment in target_summary.get("attachment_files") or []:
        attachment_path = _resolve_optional_path(raw_attachment)
        expected_hash = str(expected_attachment_hashes.get(str(attachment_path)) or "")
        if not expected_hash:
            raise IntakeError("Prepared review is missing attachment content evidence. Prepare the PDF again from the reviewed request.")
        if not hmac.compare_digest(_prepared_file_sha256(attachment_path, "attachment"), expected_hash):
            raise IntakeError("Prepared attachment changed after review. Prepare the PDF again from the reviewed request.")
    return dict(review)


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
    after: dict[str, Any] | None,
    reason: str = "",
) -> dict[str, Any]:
    changed_at = datetime.now(timezone.utc).isoformat()
    changes = diff_json_values(before or {}, after or {})
    if before is None and after is not None:
        action = "created"
    elif before is not None and after is None:
        action = "deleted"
    else:
        action = "updated" if changes else "unchanged"
    after_hash = stable_json_hash(after) if after is not None else ""
    return {
        "change_id": f"{timestamp_slug()}_{(after_hash or stable_json_hash(before or {}))[:12]}",
        "changed_at": changed_at,
        "profile_key": profile_key,
        "action": action,
        "reason": str(reason or "").strip(),
        "before_hash": stable_json_hash(before) if before is not None else "",
        "after_hash": after_hash,
        "before_profile": copy.deepcopy(before) if before is not None else None,
        "after_profile": copy.deepcopy(after) if after is not None else None,
        "changes": changes,
        "send_allowed": False,
    }


def reference_change_payload(
    *,
    reference_kind: str,
    record_key: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reason: str = "",
) -> dict[str, Any]:
    changed_at = datetime.now(timezone.utc).isoformat()
    changes = diff_json_values(before or {}, after or {})
    if before is None and after is not None:
        action = "created"
    elif before is not None and after is None:
        action = "deleted"
    else:
        action = "updated" if changes else "unchanged"
    after_hash = stable_json_hash(after) if after is not None else ""
    return {
        "change_id": f"{timestamp_slug()}_{(after_hash or stable_json_hash(before or {}))[:12]}",
        "changed_at": changed_at,
        "reference_kind": reference_kind,
        "record_key": record_key,
        "profile_key": f"{reference_kind}:{record_key}",
        "action": action,
        "reason": str(reason or "").strip(),
        "before_hash": stable_json_hash(before) if before is not None else "",
        "after_hash": after_hash,
        "before_record": copy.deepcopy(before) if before is not None else None,
        "after_record": copy.deepcopy(after) if after is not None else None,
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
        if not claim and not intake.get('travel_group_id'):
            intake.pop("transport", None)
        return

    if field == 'claim_interpreting':
        intake[field] = coerce_answer_bool(value)
        return

    if field == 'claim_options':
        choices = {'both': (True, True), 'interpreting-only': (True, False), 'travel-only': (False, True)}
        flags = choices.get(value.lower())
        if flags is None:
            raise IntakeError('Choose both, interpreting-only, or travel-only.')
        intake['claim_interpreting'], intake['claim_transport'] = flags
        return

    if field == "transport.km_one_way":
        set_nested_value(intake, field, coerce_answer_int(value))
        return

    if field == "payment_entity":
        if intake.get("photo_defaults_applied") and value != intake.get("payment_entity"):
            for routing_field in ("addressee", "recipient_email", "court_email", "court_email_key", "recipient_override_reason", "court_email_override_reason"):
                intake[routing_field] = ""
        intake["payment_entity"] = value
        if not str(intake.get("addressee") or "").strip():
            intake["addressee"] = _default_addressee(value)
        return

    if field == "recipient_email" and intake.get("photo_defaults_applied"):
        for routing_field in ("court_email", "court_email_key", "recipient_override_reason", "court_email_override_reason"):
            intake[routing_field] = ""
        intake["recipient_email"] = value
        return

    if field in {'service_place', 'service_entity'} and (intake.get('photo_defaults_applied') or {}).get('service_place'):
        intake[field] = value
        other = 'service_entity' if field == 'service_place' else 'service_place'
        if not str(intake.get(other) or '').strip():
            intake[other] = value
        reconcile_photo_venue_edit(intake)
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

    review = review_intake_with_profile_evidence(intake, paths)
    return {
        **review,
        "intake": review.get("intake", intake),
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


def draft_lifecycle_for_email_group(underlying_requests: Any, paths: AppPaths) -> dict[str, Any]:
    if not isinstance(underlying_requests, list) or not underlying_requests or any(not isinstance(row, dict) for row in underlying_requests):
        raise IntakeError("Email group active check requires a nonempty underlying_requests array of objects.")
    checks = []
    identities = set()
    for row in underlying_requests:
        identity = _intake_identity_payload(row)
        key = request_identity_key(identity)
        if not identity['case_number'] or not identity['service_date'] or key in identities:
            raise IntakeError("Email group active check has missing or repeated request identities.")
        identities.add(key)
        checks.append({**identity, **draft_lifecycle_for_intake(identity, paths)})
    active = {}
    duplicates = []
    for check in checks:
        for draft in check['active_gmail_drafts']:
            active[str(draft.get('draft_id') or '')] = draft
        duplicates.extend(check['duplicate_records'])
    blocked = any(check['status'] != 'clear' for check in checks)
    replacement = blocked and all(check['status'] == 'clear' or check['replacement_allowed'] for check in checks)
    return {"status": "blocked" if blocked else "clear", "message": "One or more group requests have an existing draft or duplicate blocker." if blocked else "All email group requests are clear.",
            "member_checks": checks, "active_gmail_drafts": list(active.values()),
            "duplicate": duplicates[0] if duplicates else None, "duplicate_records": duplicates,
            "replacement_allowed": replacement, "can_prepare": not blocked, "can_create_new_draft": not blocked,
            "needs_correction": blocked and replacement, "blocking_statuses": sorted(BLOCKING_DUPLICATE_STATUSES), "send_allowed": False}


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
        question_word = "question" if count == 1 else "questions"
        return next_safe_action(
            state="answer_questions",
            title=f"Answer {count} {question_word} before PDF creation",
            detail=f"{count} numbered {question_word} need an answer. Provide short numbered replies, then apply the answers and review again.",
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


def prepared_next_safe_action(packet_mode: bool = False, gmail_status: dict[str, Any] | None = None) -> dict[str, Any]:
    attachment_label = "packet PDF" if packet_mode else "generated PDF"
    if (
        isinstance(gmail_status, dict)
        and gmail_status.get("recommended_mode") == "gmail_api"
        and bool(gmail_status.get("draft_create_ready"))
    ):
        return next_safe_action(
            state="review_gmail_draft_args",
            title="Create Gmail Draft in-app",
            detail=(
                f"Inspect the {attachment_label}, recipient, body, and attachment array. Then tick the Gmail handoff checklist and use the guarded Create Gmail Draft action. Manual Draft Handoff remains available as a fallback."
            ),
            button_id="create-gmail-api-draft",
            blocked=False,
        )
    return next_safe_action(
        state="review_gmail_draft_args",
        title="Use Manual Draft Handoff",
        detail=(
            f"Inspect the {attachment_label}, recipient, body, and attachment array. Then use the exact _create_draft args in Manual Draft Handoff and record the returned Gmail IDs locally."
        ),
        button_id="record-parsed-prepared-draft",
        blocked=False,
    )


def _legacy_profile_defaults(paths: AppPaths) -> dict[str, Any]:
    return _read_json_object_if_exists(paths.profile)


def load_personal_profiles(paths: AppPaths) -> dict[str, Any]:
    return load_profile_store(paths.personal_profiles, paths.profile, paths.known_destinations)


def personal_profiles_summary(paths: AppPaths) -> dict[str, Any]:
    return profile_summary(load_personal_profiles(paths))


def selected_personal_profile(paths: AppPaths, intake: dict[str, Any] | None = None) -> dict[str, Any]:
    store = load_personal_profiles(paths)
    profile_id = str((intake or {}).get("personal_profile_id") or "").strip()
    return find_profile(store, profile_id)


def generator_profile_for_intake(paths: AppPaths, intake: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = selected_personal_profile(paths, intake)
    return profile_to_generator_profile(profile, _legacy_profile_defaults(paths))


def _normalize_source_case_confirmation(intake: dict[str, Any]) -> None:
    if intake.get('case_number_requires_confirmation') or 'source_case_numbers' in intake:
        value = valid_source_case(intake.get('case_number'))
        intake['case_number'] = value
        intake['case_number_requires_confirmation'] = not bool(value)


def effective_intake_for_profile(intake: dict[str, Any], paths: AppPaths) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    intake = copy.deepcopy(intake)
    preserve_review_field_clears(intake, intake)
    reconcile_photo_venue_edit(intake)
    _normalize_source_case_confirmation(intake)
    profile = selected_personal_profile(paths, intake)
    effective, provenance = apply_profile_defaults_to_intake(intake, profile)
    preserve_review_field_clears(intake, effective)
    if 'transport.km_one_way' in effective.get('review_cleared_fields', []):
        provenance['applied'] = [field for field in provenance['applied'] if field != 'transport.km_one_way']
        provenance['distance_source'] = ''
    generator_profile = profile_to_generator_profile(profile, _legacy_profile_defaults(paths))
    saved_closing_city = str(_legacy_profile_defaults(paths).get("default_closing_city") or "").strip()
    if intake.get("photo_defaults_applied") and not str(effective.get("closing_city") or "").strip() and saved_closing_city:
        effective["closing_city"] = saved_closing_city
        provenance["applied"].append("closing_city")
    return effective, generator_profile, provenance


def personal_profile_payload(profile: dict[str, Any], *, is_main: bool = False) -> dict[str, Any]:
    return {
        **profile,
        "display_name": profile_display_name(profile),
        "is_main": is_main,
        "missing_required_fields": missing_required_fields(profile),
    }


def new_personal_profile(paths: AppPaths) -> dict[str, Any]:
    profile = blank_profile()
    return {
        "status": "created",
        "profile": personal_profile_payload(profile),
        "write_allowed": False,
        "send_allowed": False,
    }


def save_personal_profile(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    incoming = profile_from_mapping(payload.get("profile") if isinstance(payload.get("profile"), dict) else payload)
    validate_profile(incoming)
    store = load_personal_profiles(paths)
    profiles = [
        copy.deepcopy(incoming) if str(profile.get("id") or "") == incoming["id"] else profile
        for profile in store.get("profiles", [])
        if isinstance(profile, dict)
    ]
    if incoming["id"] not in {str(profile.get("id") or "") for profile in profiles}:
        profiles.append(copy.deepcopy(incoming))
    primary_id = incoming["id"] if bool(payload.get("make_main") or payload.get("is_main")) else store.get("primary_profile_id")
    saved = save_profile_store(
        paths.personal_profiles,
        paths.profile,
        {"schema_version": 1, "primary_profile_id": primary_id, "profiles": profiles},
        legacy_defaults=_legacy_profile_defaults(paths),
    )
    return {
        "status": "saved",
        "message": f"Saved personal profile {profile_display_name(incoming)}.",
        "profile": personal_profile_payload(incoming, is_main=saved.get("primary_profile_id") == incoming["id"]),
        "profiles": profile_summary(saved),
        "write_allowed": True,
        "send_allowed": False,
    }


def set_main_personal_profile(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    profile_id = str(payload.get("profile_id") or payload.get("id") or "").strip()
    if not profile_id:
        raise IntakeError("Missing personal profile id.")
    store = load_personal_profiles(paths)
    profile = find_profile(store, profile_id)
    saved = save_profile_store(
        paths.personal_profiles,
        paths.profile,
        {"schema_version": 1, "primary_profile_id": profile_id, "profiles": store.get("profiles", [])},
        legacy_defaults=_legacy_profile_defaults(paths),
    )
    return {
        "status": "saved",
        "message": f"{profile_display_name(profile)} is now the main personal profile.",
        "profiles": profile_summary(saved),
        "write_allowed": True,
        "send_allowed": False,
    }


def delete_personal_profile(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    profile_id = str(payload.get("profile_id") or payload.get("id") or "").strip()
    if not profile_id:
        raise IntakeError("Missing personal profile id.")
    store = load_personal_profiles(paths)
    profiles = [profile for profile in store.get("profiles", []) if isinstance(profile, dict)]
    if len(profiles) <= 1:
        raise IntakeError("Cannot delete the only personal profile.")
    remaining = [profile for profile in profiles if str(profile.get("id") or "") != profile_id]
    if len(remaining) == len(profiles):
        raise IntakeError(f"Unknown personal profile: {profile_id}")
    primary_id = str(store.get("primary_profile_id") or "")
    if primary_id == profile_id:
        primary_id = str(remaining[0].get("id") or "")
    saved = save_profile_store(
        paths.personal_profiles,
        paths.profile,
        {"schema_version": 1, "primary_profile_id": primary_id, "profiles": remaining},
        legacy_defaults=_legacy_profile_defaults(paths),
    )
    return {
        "status": "deleted",
        "message": "Personal profile deleted locally. LegalPDF Translate was not modified.",
        "profiles": profile_summary(saved),
        "write_allowed": True,
        "send_allowed": False,
    }


def preview_legalpdf_personal_profile_import(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    incoming = load_legalpdf_profiles(payload)
    current = load_personal_profiles(paths)
    _merged, changes = merge_profile_stores(current, incoming)
    return {
        "status": "previewed",
        "message": "LegalPDF personal profile import preview is ready. No local files were changed and LegalPDF was not modified.",
        "incoming_profile_count": len(incoming.get("profiles") or []),
        "current_profile_count": len(current.get("profiles") or []),
        "primary_profile_id": incoming.get("primary_profile_id"),
        "changes": changes,
        "confirmation_phrase": LEGALPDF_PROFILE_IMPORT_CONFIRMATION_PHRASE,
        "write_allowed": False,
        "legalpdf_write_allowed": False,
        "send_allowed": False,
    }


def apply_legalpdf_personal_profile_import(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    if not bool(payload.get("confirm_import")):
        raise IntakeError("LegalPDF profile import requires confirm_import=true and the exact confirmation phrase.")
    phrase = str(payload.get("confirmation_phrase") or "").strip()
    if phrase != LEGALPDF_PROFILE_IMPORT_CONFIRMATION_PHRASE:
        raise IntakeError(f'LegalPDF profile import requires confirmation phrase "{LEGALPDF_PROFILE_IMPORT_CONFIRMATION_PHRASE}".')
    reason = str(payload.get("import_reason") or payload.get("reason") or "").strip()
    if len(reason) < 8:
        raise IntakeError("LegalPDF profile import requires a short import_reason.")
    incoming = load_legalpdf_profiles(payload)
    current = load_personal_profiles(paths)
    merged, changes = merge_profile_stores(current, incoming)
    pre_import_backup = backup_payload(paths)
    pre_import_backup["reason"] = f"Automatic backup before LegalPDF personal profile import: {reason}"
    backup_file = write_backup_file(pre_import_backup, paths, prefix="pre-legalpdf-profiles-import-backup")
    saved = save_profile_store(
        paths.personal_profiles,
        paths.profile,
        merged,
        legacy_defaults=_legacy_profile_defaults(paths),
    )
    report = personal_profile_import_report(changes, reason, str(backup_file))
    paths.integration_report_output_dir.mkdir(parents=True, exist_ok=True)
    report_id = f"legalpdf-personal-profiles-import-{timestamp_slug()}-{secrets.token_hex(4)}"
    report_file = paths.integration_report_output_dir / f"{report_id}.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "imported",
        "message": "LegalPDF personal profiles were copied into this Honorários app. LegalPDF Translate was not modified.",
        "profiles": profile_summary(saved),
        "changes": changes,
        "pre_import_backup_file": str(backup_file),
        "import_report_file": str(report_file),
        "backup_status": backup_status_payload(paths),
        "write_allowed": True,
        "legalpdf_write_allowed": False,
        "send_allowed": False,
    }


def gmail_api_status(paths: AppPaths) -> dict[str, Any]:
    return gmail_status_payload(paths.gmail_config)


def gmail_api_config_save(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    return save_gmail_local_config(payload, paths.gmail_config)


def gmail_api_oauth_start(paths: AppPaths) -> dict[str, Any]:
    return gmail_oauth_start(paths.gmail_config)


def gmail_api_oauth_callback(*, code: str, state: str, paths: AppPaths) -> dict[str, Any]:
    return gmail_oauth_callback(code=code, state=state, config_path=paths.gmail_config)


def gmail_api_draft_verify(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    return verify_gmail_draft_exists(payload, paths.gmail_config)


def reconcile_gmail_draft_not_found(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    if not bool(payload.get("confirm_not_found")):
        raise IntakeError("Confirm the missing Gmail draft before marking the local lifecycle record as not_found.")
    reason = str(payload.get("reconciliation_reason") or payload.get("reason") or "").strip()
    if len(reason) < 8:
        raise IntakeError("Add a short reconciliation reason before marking the local lifecycle record as not_found.")

    verification = gmail_api_draft_verify(payload, paths)
    if verification.get("status") != "not_found":
        raise IntakeError("Gmail still reports this draft as existing. Local records were not changed.")

    record_payload = dict(payload)
    record_payload["status"] = "not_found"
    record_payload["notes"] = (
        "Marked not_found from Recent Work after Gmail draft verification returned not_found. "
        f"Reason: {reason}"
    )
    record_payload.pop("confirm_not_found", None)
    record_payload.pop("reconciliation_reason", None)
    record = record_draft(record_payload, paths)
    return {
        **record,
        "lifecycle_status": "not_found",
        "verification": verification,
        "gmail_api_action": "users.drafts.get",
        "draft_only": True,
        "send_allowed": False,
        "write_allowed": True,
        "managed_data_changed": True,
        "local_records_changed": True,
    }


def _load_prepared_draft_payload(payload_path: str | Path) -> tuple[Path, dict[str, Any]]:
    raw_path = Path(str(payload_path or "").strip())
    if not str(raw_path):
        raise IntakeError("Gmail draft creation requires a prepared draft payload path.")
    path = raw_path if raw_path.is_absolute() else ROOT / raw_path
    absolute = path.resolve()
    if not absolute.exists() or not absolute.is_file():
        raise IntakeError(f"Prepared draft payload does not exist: {absolute}")
    try:
        payload = json.loads(absolute.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntakeError(f"Prepared draft payload is invalid JSON: {absolute}") from exc
    if not isinstance(payload, dict):
        raise IntakeError(f"Prepared draft payload must be a JSON object: {absolute}")
    errors = validate_draft_payload(payload)
    if errors:
        raise IntakeError("Prepared draft payload is not Gmail-ready: " + "; ".join(errors))
    return absolute, payload


def _prepared_payload_request_identities(draft_payload: dict[str, Any]) -> list[dict[str, Any]]:
    source_requests = draft_payload.get("underlying_requests")
    if not isinstance(source_requests, list) or not source_requests:
        source_requests = [draft_payload]

    identities: list[dict[str, Any]] = []
    for source in source_requests:
        if not isinstance(source, dict):
            continue
        case_number = str(source.get("case_number") or "").strip()
        service_date = str(source.get("service_date") or "").strip()
        if not case_number or not service_date:
            continue
        identity: dict[str, Any] = {
            "case_number": case_number,
            "service_date": service_date,
            "service_period_label": str(source.get("service_period_label") or "").strip(),
            "service_start_time": str(source.get("service_start_time") or "").strip(),
            "service_end_time": str(source.get("service_end_time") or "").strip(),
        }
        identity.update({key: source[key] for key in ('claim_interpreting', 'claim_transport', 'travel_group_id', 'travel_group_binding') if key in source})
        identities.append(identity)

    if not identities:
        raise IntakeError("Prepared Gmail payload is missing case/date identity for duplicate checks.")
    return identities


def _gmail_correction_reason(payload: dict[str, Any]) -> str:
    for key in ("correction_reason", "reason", "notes"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _lifecycle_blocking_draft_ids(lifecycle: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    active = lifecycle.get("active_gmail_drafts") if isinstance(lifecycle.get("active_gmail_drafts"), list) else []
    duplicates = lifecycle.get("duplicate_records") if isinstance(lifecycle.get("duplicate_records"), list) else []
    for record in [*active, *duplicates]:
        if not isinstance(record, dict):
            continue
        draft_id = str(record.get("draft_id") or "").strip()
        status = str(record.get("status") or "").strip()
        if draft_id and status in {"active", "drafted"}:
            ids.append(draft_id)
    return sorted(set(ids))


def _assert_gmail_create_duplicate_clear(
    *,
    request_payload: dict[str, Any],
    draft_payload: dict[str, Any],
    paths: AppPaths,
) -> dict[str, Any]:
    identities = _prepared_payload_request_identities(draft_payload)
    try:
        validate_superseded_request_coverage(identities, load_draft_log(paths.draft_log), _coerce_supersedes(request_payload.get('supersedes')))
    except ValueError as exc:
        raise IntakeError('Draft replacement blocked before contacting Gmail: ' + str(exc)) from exc
    try:
        validate_travel_payload_groups(identities, prior_requests=recorded_claims(paths))
    except ClaimError as exc:
        raise IntakeError('Gmail draft creation blocked before contacting Gmail: ' + str(exc)) from exc
    lifecycles: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for identity in identities:
        lifecycle = draft_lifecycle_for_intake(identity, paths)
        lifecycle["request_identity"] = duplicate_key_payload(identity)
        lifecycles.append(lifecycle)
        if lifecycle.get("status") != "clear":
            blockers.append(lifecycle)

    if not blockers:
        return {
            "requests": [duplicate_key_payload(identity) for identity in identities],
            "lifecycles": lifecycles,
            "blockers": [],
            "correction_mode": False,
        }

    sent_blockers = [
        blocker for blocker in blockers
        if not bool(blocker.get("replacement_allowed"))
    ]
    if sent_blockers:
        descriptions = [
            " · ".join(str(item) for item in blocker.get("request_identity", {}).values() if item)
            for blocker in sent_blockers
        ]
        raise IntakeError(
            "Gmail draft creation blocked before contacting Gmail because a sent or non-replaceable "
            f"request already exists: {'; '.join(descriptions)}."
        )

    supersedes = _coerce_supersedes(request_payload.get("supersedes"))
    correction_reason = _gmail_correction_reason(request_payload)
    if not supersedes or len(correction_reason) < 8:
        raise IntakeError(
            "Gmail draft creation blocked before contacting Gmail because an active/drafted request already exists. "
            "Use correction mode with supersedes plus a short correction reason before creating a replacement draft."
        )

    required_supersedes = sorted(set().union(*[_lifecycle_blocking_draft_ids(blocker) for blocker in blockers]))
    if required_supersedes:
        missing = [draft_id for draft_id in required_supersedes if draft_id not in supersedes]
        if missing:
            raise IntakeError(
                "Correction mode must supersede the blocking draft ID(s) before Gmail is contacted: "
                + ", ".join(missing)
            )
        draft_log_ids = {
            str(record.get("draft_id") or "").strip()
            for record in load_draft_log(paths.draft_log)
            if str(record.get("draft_id") or "").strip()
        }
        unknown = [draft_id for draft_id in supersedes if draft_id not in draft_log_ids]
        if unknown:
            raise IntakeError(
                "Correction mode references draft ID(s) that are not in the local draft log, so Gmail was not contacted: "
                + ", ".join(unknown)
            )
    elif any(blocker.get("duplicate_records") for blocker in blockers):
        raise IntakeError(
            "Gmail draft creation blocked before contacting Gmail because a drafted duplicate has no draft ID to supersede. "
            "Mark the old record as superseded/trashed first, then create the replacement."
        )

    return {
        "requests": [duplicate_key_payload(identity) for identity in identities],
        "lifecycles": lifecycles,
        "blockers": blockers,
        "correction_mode": True,
        "correction_reason": correction_reason,
        "supersedes": supersedes,
    }


def _gmail_create_confirmation(
    *,
    gmail_result: dict[str, Any],
    record_result: dict[str, Any],
    payload_path: Path,
    duplicate_check: dict[str, Any],
    paths: AppPaths,
) -> dict[str, Any]:
    attachment_files = [str(item) for item in gmail_result.get("attachment_files") or []]
    attachment_hashes = dict(gmail_result.get("attachment_sha256") or {})
    return {
        "status": "created",
        "provider": "gmail_api",
        "gmail_api_action": gmail_result.get("gmail_api_action", "users.drafts.create"),
        "fake_mode": bool(gmail_result.get("fake_mode")),
        "draft_id": gmail_result.get("draft_id", ""),
        "message_id": gmail_result.get("message_id", ""),
        "thread_id": gmail_result.get("thread_id", ""),
        "to": gmail_result.get("to", ""),
        "subject": gmail_result.get("subject", ""),
        "attachment_files": attachment_files,
        "attachment_basenames": list(gmail_result.get("attachment_basenames") or [Path(item).name for item in attachment_files]),
        "attachment_sha256": attachment_hashes,
        "attachment_count": len(attachment_files),
        "duplicate_records_created": list(record_result.get("duplicate_keys") or []),
        "recorded_duplicate_count": int(record_result.get("recorded_duplicate_count") or 0),
        "superseded_drafts": list(record_result.get("superseded_drafts") or []),
        "duplicate_check_requests": list(duplicate_check.get("requests") or []),
        "correction_mode": bool(duplicate_check.get("correction_mode")),
        "draft_payload": str(payload_path),
        "draft_log_path": str(paths.draft_log.resolve()),
        "duplicate_index_path": str(paths.duplicate_index.resolve()),
        "draft_only": True,
        "send_allowed": False,
    }


@contextlib.contextmanager
def _gmail_create_lock_for_payload(draft_payload: dict[str, Any]):
    identities = [
        duplicate_key_payload(identity)
        for identity in _prepared_payload_request_identities(draft_payload)
    ]
    keys = sorted({json.dumps(identity, ensure_ascii=True, sort_keys=True) for identity in identities})
    with _GMAIL_CREATE_LOCKS_GUARD:
        locks = [_GMAIL_CREATE_LOCKS.setdefault(key, threading.Lock()) for key in keys]
    # Overlapping grouped and individual requests must serialize on the same child identity.
    with contextlib.ExitStack() as stack:
        for lock in locks:
            stack.enter_context(lock)
        yield


def create_and_record_gmail_api_draft(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    if not bool(payload.get("gmail_handoff_reviewed")):
        raise IntakeError("Review the PDF preview and exact Gmail draft args before creating a Gmail draft.")
    if payload.get("recover_attempt_id") or payload.get("resolve_attempt_id"):
        return reconcile_gmail_create_attempt(payload, paths)
    raw_payload_path = payload.get("payload") or payload.get("draft_payload")
    prepared_review = require_current_prepared_review(payload, raw_payload_path, paths)
    supersedes = _coerce_supersedes(payload.get("supersedes"))
    explicit_correction_reason = str(payload.get("correction_reason") or payload.get("reason") or "").strip()
    if (supersedes or explicit_correction_reason) and not bool(prepared_review.get("correction_mode")):
        raise IntakeError("Gmail draft correction mode requires a prepared review created in correction mode.")
    prepared_correction_reason = str(prepared_review.get("correction_reason") or "").strip()
    if explicit_correction_reason and prepared_correction_reason and explicit_correction_reason != prepared_correction_reason:
        raise IntakeError("Gmail draft correction reason does not match the prepared review. Prepare the replacement again.")
    payload_path, draft_payload = _load_prepared_draft_payload(raw_payload_path)
    with attempt_lock(paths.draft_log), _gmail_create_lock_for_payload(draft_payload):
        attempts = load_attempts(paths.draft_log)
        prior = pending_attempt(attempts, _prepared_payload_request_identities(draft_payload))
        if prior:
            return gmail_attempt_response(prior)
        duplicate_check = _assert_gmail_create_duplicate_clear(
            request_payload=payload,
            draft_payload=draft_payload,
            paths=paths,
        )
        manifest = load_json(Path(prepared_review["manifest"]))
        target = next(item for item in manifest["prepared_review_material"]["targets"]
                      if item["draft_payload"] == str(payload_path))
        attempt = new_attempt(_prepared_payload_request_identities(draft_payload),
                              payload=str(payload_path), target=target, prepared_review=prepared_review,
                              gmail_create_draft_args=draft_payload["gmail_create_draft_args"],
                              request_payload={key: payload[key] for key in ("notes", "supersedes", "correction_reason") if key in payload})
        attempts.append(attempt)
        # A durable reservation precedes the external side effect. A crash or lost
        # response therefore cannot silently make a second create safe to retry.
        save_attempts(paths.draft_log, attempts)
        try:
            result = create_gmail_draft_from_payload(draft_payload, paths.gmail_config)
        except GmailDraftCreateError as exc:
            update_attempt(attempt, state="uncertain" if exc.may_have_created else "not_created", error=str(exc))
            save_attempts(paths.draft_log, attempts)
            if exc.may_have_created:
                return gmail_attempt_response(attempt)
            raise
        except IntakeError as exc:
            # MIME validation and OAuth fail before users.drafts.create is called.
            update_attempt(attempt, state="not_created", error=str(exc))
            save_attempts(paths.draft_log, attempts)
            raise
        except Exception as exc:
            update_attempt(attempt, state="uncertain", error="The creation outcome could not be confirmed.")
            save_attempts(paths.draft_log, attempts)
            return gmail_attempt_response(attempt)
        update_attempt(attempt, state="created_unrecorded", gmail_result=result)
        try:
            save_attempts(paths.draft_log, attempts)
        except OSError:
            # The earlier reservation still blocks another create. Return known
            # IDs even when the disk cannot persist this second checkpoint.
            return gmail_attempt_response(attempt, error="Gmail created the draft, but its returned IDs could not be saved. Copy these IDs and recover local recording after fixing local storage.")
        record_payload = {
            "payload": str(payload_path),
            "draft_id": result["draft_id"],
            "message_id": result["message_id"],
            "thread_id": result.get("thread_id", ""),
            "status": "active",
            "notes": str(payload.get("notes") or payload.get("correction_reason") or "Created through the local Gmail Draft API.").strip(),
            "supersedes": _coerce_supersedes(payload.get("supersedes")),
            "prepared_manifest": prepared_review["manifest"],
            "prepared_review_token": prepared_review["prepared_review_token"],
            "review_fingerprint": prepared_review["review_fingerprint"],
        }
        try:
            record_result = record_draft(record_payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            update_attempt(attempt, error=str(exc))
            with contextlib.suppress(OSError):
                save_attempts(paths.draft_log, attempts)
            return gmail_attempt_response(attempt)
        update_attempt(attempt, state="recorded")
        with contextlib.suppress(OSError):
            save_attempts(paths.draft_log, attempts)
        confirmation = _gmail_create_confirmation(
            gmail_result=result,
            record_result=record_result,
            payload_path=payload_path,
            duplicate_check=duplicate_check,
            paths=paths,
        )
        return {
            "status": "created",
            "message": "Gmail draft created and recorded locally. Review and send it manually in Gmail.",
            "gmail_api_action": result["gmail_api_action"],
            "draft_id": result["draft_id"],
            "message_id": result["message_id"],
            "thread_id": result.get("thread_id", ""),
            "to": result["to"],
            "subject": result["subject"],
            "attachment_basenames": result["attachment_basenames"],
            "attachment_files": result["attachment_files"],
            "attachment_sha256": result["attachment_sha256"],
            "draft_payload": str(payload_path),
            "record": record_result,
            "confirmation": confirmation,
            "duplicate_check": duplicate_check,
            "prepared_review": prepared_review,
            "duplicate_keys": record_result.get("duplicate_keys", []),
            "recorded_duplicate_count": record_result.get("recorded_duplicate_count", 0),
            "fake_mode": bool(result.get("fake_mode")),
            "draft_only": True,
            "send_allowed": False,
        }


def gmail_attempt_response(attempt: dict[str, Any], *, error: str = "") -> dict[str, Any]:
    result = attempt.get("gmail_result") or {}
    confirmed = bool(result.get("draft_id") and result.get("message_id"))
    status = "created_unrecorded" if confirmed else "creation_uncertain"
    message = ("Gmail created this draft, but local recording is incomplete. Finish local recording; do not create another draft."
               if confirmed else "Gmail may already have created this email. Check Gmail, then record the existing draft or explicitly confirm that no draft exists. Another create is blocked until then.")
    return {**result, "status": status, "message": error or message,
            "recording_error": str(attempt.get("error") or ""), "attempt_id": attempt["attempt_id"],
            "draft_payload": attempt["payload"], "create_retry_allowed": False,
            "local_recording_recovery_allowed": confirmed, "uncertain_resolution_required": not confirmed,
            "gmail_create_draft_args": dict(attempt.get("gmail_create_draft_args") or {}),
            "draft_only": True, "send_allowed": False}


def _validate_attempt_artifacts(attempt: dict[str, Any]) -> dict[str, Any]:
    target = attempt["target"]
    payload_path = Path(attempt["payload"])
    if file_sha256(payload_path) != target["draft_payload_sha256"]:
        raise IntakeError("The original attempted email payload changed. Recover its saved original files before recording this draft.")
    for raw_path, expected in {**target.get("attachment_sha256", {}), **target.get("child_payload_sha256", {})}.items():
        if file_sha256(Path(raw_path)) != expected:
            raise IntakeError("An original attempted attachment or child payload changed. Recover the reviewed original before recording.")
    loaded = load_json(payload_path)
    errors = validate_draft_payload(loaded)
    if errors:
        raise IntakeError("The original attempted email is invalid: " + "; ".join(errors))
    return loaded


def reconcile_gmail_create_attempt(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    attempt_id = str(payload.get("recover_attempt_id") or payload.get("resolve_attempt_id") or "")
    with attempt_lock(paths.draft_log):
        attempts = load_attempts(paths.draft_log)
        attempt = next((item for item in attempts if item["attempt_id"] == attempt_id), None)
        if not attempt or attempt.get("state") in {"not_created", "confirmed_not_created"}:
            raise IntakeError("This Gmail attempt is not pending recovery.")
        if payload.get("resolve_attempt_id"):
            if attempt.get("gmail_result") or attempt.get("state") == "recorded":
                raise IntakeError("This attempt has confirmed Gmail IDs. Finish local recording instead.")
            if payload.get("confirmation_phrase") != "I CHECKED GMAIL: NO DRAFT" or not str(payload.get("resolution_reason") or "").strip():
                raise IntakeError("Check Gmail first, then confirm I CHECKED GMAIL: NO DRAFT and give a short reason before retrying creation.")
            allowed_old_ids = set(_coerce_supersedes(attempt.get("request_payload", {}).get("supersedes")))
            for request in attempt["requests"]:
                lifecycle = draft_lifecycle_for_intake(request, paths)
                existing_ids = set(_lifecycle_blocking_draft_ids(lifecycle))
                if lifecycle["status"] != "clear" and (not existing_ids or not existing_ids.issubset(allowed_old_ids)):
                    raise IntakeError("Local history already records one of these requests. Reconcile that draft before confirming no draft exists.")
            update_attempt(attempt, state="confirmed_not_created", resolution_reason=str(payload["resolution_reason"]).strip())
            save_attempts(paths.draft_log, attempts)
            return {"status": "not_created", "message": "Your no-draft check was recorded. You can now create the reviewed email.",
                    "attempt_id": attempt_id, "create_retry_allowed": True,
                    "gmail_api_action": "local_attempt_resolution", "local_records_changed": True, "send_allowed": False}
        draft_payload = _validate_attempt_artifacts(attempt)
        result = attempt.get("gmail_result") or {}
        if not result:
            if payload.get("confirmation_phrase") != "I CHECKED THE EXISTING GMAIL DRAFT":
                raise IntakeError("Check the existing Gmail draft's recipient, text and every attachment against the original attempted email before recording its IDs.")
            draft_id = str(payload.get("draft_id") or "").strip()
            message_id = str(payload.get("message_id") or "").strip()
            if not draft_id or not message_id:
                raise IntakeError("Enter both returned Gmail draft and message IDs for the existing draft.")
            args = draft_payload["gmail_create_draft_args"]
            result = {"draft_id": draft_id, "message_id": message_id, "thread_id": str(payload.get("thread_id") or ""),
                      "gmail_api_action": "manual_existing_draft_record", "to": args["to"], "subject": args["subject"],
                      "attachment_files": draft_payload["attachment_files"], "attachment_sha256": draft_payload.get("attachment_sha256", {}),
                      "attachment_basenames": draft_payload.get("attachment_basenames", []), "draft_only": True, "send_allowed": False}
            update_attempt(attempt, state="created_unrecorded", gmail_result=result)
            save_attempts(paths.draft_log, attempts)
        record_payload = {**attempt.get("request_payload", {}), "payload": attempt["payload"], "status": "active",
                          "draft_id": result["draft_id"], "message_id": result["message_id"], "thread_id": result.get("thread_id", "")}
        previous = next((row for row in load_draft_log(paths.draft_log) if row.get("draft_id") == result["draft_id"]), None)
        if previous and previous.get("status") not in {"active", "drafted"}:
            raise IntakeError("This Gmail draft was already sent or retired locally. Recovery cannot restore it to active.")
        try:
            recorded = record_draft(record_payload, paths, _trusted_prepared_recovery=attempt["prepared_review"])
        except (IntakeError, OSError, ValueError) as exc:
            update_attempt(attempt, error=str(exc))
            with contextlib.suppress(OSError):
                save_attempts(paths.draft_log, attempts)
            return gmail_attempt_response(attempt)
        update_attempt(attempt, state="recorded")
        with contextlib.suppress(OSError):
            save_attempts(paths.draft_log, attempts)
        recovery_result = {**result, "gmail_api_action": "local_record_recovery"}
        confirmation = _gmail_create_confirmation(gmail_result=recovery_result, record_result=recorded, payload_path=Path(attempt["payload"]),
                                                  duplicate_check={"requests": attempt["requests"]}, paths=paths)
        return {**recovery_result, "status": "created", "message": "The existing Gmail draft is now recorded locally. No new Gmail draft was created.",
                "attempt_id": attempt_id, "recovered_existing_draft": True, "draft_payload": attempt["payload"],
                "record": recorded, "confirmation": confirmation, "duplicate_keys": recorded["duplicate_keys"],
                "recorded_duplicate_count": recorded["recorded_duplicate_count"], "local_records_changed": True, "send_allowed": False}


def manual_handoff_packet(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    raw_payload_path = payload.get("payload") or payload.get("draft_payload")
    prepared_review = require_current_prepared_review(payload, raw_payload_path, paths)
    payload_path, draft_payload = _load_prepared_draft_payload(raw_payload_path)
    with attempt_lock(paths.draft_log):
        if pending_attempt(load_attempts(paths.draft_log), _prepared_payload_request_identities(draft_payload)):
            raise IntakeError("Recover the pending Gmail attempt for these requests before building another manual handoff.")
    if draft_payload.get('email_grouping') == 'source':
        if _coerce_supersedes(payload.get('supersedes')) and not prepared_review.get('correction_mode'):
            raise IntakeError('Group replacement requires a prepared review created in correction mode.')
        if prepared_review.get('correction_reason') and _gmail_correction_reason(payload) != prepared_review['correction_reason']:
            raise IntakeError('Correction reason does not match the prepared review.')
        _assert_gmail_create_duplicate_clear(request_payload=payload, draft_payload=draft_payload, paths=paths)
    args = draft_payload.get("gmail_create_draft_args")
    if not isinstance(args, dict):
        raise IntakeError("Prepared draft payload is missing gmail_create_draft_args.")

    attachment_files = [str(item) for item in args.get("attachment_files") or []]
    attachment_basenames = [Path(item).name for item in attachment_files]
    attachment_hashes: dict[str, str] = {}
    for item in attachment_files:
        path = Path(item)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        attachment_hashes[str(path)] = digest.hexdigest()

    args_json = json.dumps(args, ensure_ascii=False, indent=2)
    prompt = "\n".join([
        "Create a Gmail draft only using `_create_draft` with these exact arguments.",
        "Leave it as a draft for manual review.",
        "Return draft_id, message_id, and thread_id so I can record the draft locally.",
        "",
        args_json,
    ])
    return {
        "status": "ready",
        "mode": "manual_handoff",
        "message": "Manual handoff packet ready. Copy the prompt into the draft-only Gmail connector, then paste the returned IDs back here.",
        "gmail_tool": "_create_draft",
        "payload_path": str(payload_path),
        "to": str(args.get("to") or ""),
        "subject": str(args.get("subject") or ""),
        "body": str(args.get("body") or ""),
        "attachment_files": attachment_files,
        "attachment_basenames": attachment_basenames,
        "attachment_sha256": attachment_hashes,
        "attachment_count": len(attachment_files),
        "gmail_create_draft_args": args,
        "copyable_args_json": args_json,
        "copyable_prompt": prompt,
        "prepared_review": prepared_review,
        "record_next_step": "After `_create_draft` returns IDs, paste the response into Manual Draft Handoff and record locally.",
        "draft_only": True,
        "send_allowed": False,
        "write_allowed": False,
        "managed_data_changed": False,
    }


def load_app_reference(paths: AppPaths) -> dict[str, Any]:
    duplicate_records = read_json_list(paths.duplicate_index)
    draft_records = read_json_list(paths.draft_log)
    return {
        "personal_profiles": personal_profiles_summary(paths),
        "service_profiles": load_profiles(paths.service_profiles),
        "court_emails": read_json_list(paths.court_emails),
        "known_destinations": load_known_destinations(paths),
        "duplicates": duplicate_records,
        "draft_log": draft_records,
        "pending_gmail_attempts": [gmail_attempt_response(attempt) for attempt in load_attempts(paths.draft_log)
                                   if attempt.get("state") not in {"recorded", "not_created", "confirmed_not_created"}],
        "profile_change_log": read_json_list(paths.profile_change_log),
        "gmail": {
            "tool": "_create_draft",
            "send_allowed": False,
            "draft_only": True,
            "api": gmail_status_payload(paths.gmail_config),
        },
        "ai": ai_status_payload(paths.ai_config),
        "backup": backup_status_payload(paths),
    }


def build_profile_intake(payload: dict[str, Any], paths: AppPaths) -> dict[str, Any]:
    profiles = load_profiles(paths.service_profiles)
    intake = build_intake(
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
    personal_profile_id = str(payload.get("personal_profile_id") or "").strip()
    if personal_profile_id:
        intake["personal_profile_id"] = personal_profile_id
    profile_name = str(payload.get("profile") or payload.get("profile_name") or "").strip()
    if profile_name:
        intake["service_profile_key"] = profile_name
    effective, _profile, _provenance = effective_intake_for_profile(intake, paths)
    return effective


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

    try:
        effective_intake, profile, profile_provenance = effective_intake_for_profile(intake, paths)
    except (IntakeError, OSError, json.JSONDecodeError) as exc:
        return {
            "status": "error",
            "message": str(exc),
            "questions": [],
            "next_safe_action": review_next_safe_action("error"),
            "send_allowed": False,
        }

    questions = missing_questions(effective_intake)
    if questions:
        return {
            "status": "needs_info",
            "message": "Missing information before PDF generation.",
            "questions": question_payload(questions),
            "question_text": format_numbered_questions(questions),
            "next_safe_action": review_next_safe_action("needs_info", questions=question_payload(questions)),
            "send_allowed": False,
        }

    duplicate = find_duplicate_record(effective_intake, paths.duplicate_index)
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
    active_drafts = active_drafts_for(effective_intake, draft_log)
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
        email_config = load_json(paths.email_config)
        court_directory = read_json_list(paths.court_emails)
        rendered = build_rendered_request(effective_intake, profile)
        resolve_email_body(effective_intake, email_config, signature_name=rendered.signature_name)
        validate_shared_travel_groups([effective_intake], prior_requests=recorded_claims(paths))
        recipient, recipient_source = resolve_recipient(effective_intake, email_config, court_directory)
    except (IntakeError, ClaimError, OSError, json.JSONDecodeError) as exc:
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
        "service_date": str(effective_intake.get("service_date") or effective_intake.get("photo_metadata_date") or ""),
        "payment_entity": str(effective_intake.get("payment_entity") or ""),
        "service_entity": str(effective_intake.get("service_entity") or effective_intake.get("service_place") or ""),
        "recipient": recipient,
        "recipient_source": recipient_source,
        "effective_intake": effective_intake,
        "personal_profile": profile_provenance,
        "draft_text": rendered_request_text(rendered),
        "questions": [],
        "next_safe_action": review_next_safe_action("ready"),
        "send_allowed": False,
    }


def planned_intake_paths(intakes: list[dict[str, Any]], paths: AppPaths) -> list[Path]:
    stamp = f'{timestamp_slug()}-{secrets.token_hex(8)}'
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
        for key in ("service_period_label", "service_start_time", "service_end_time", 'claim_interpreting', 'claim_transport', 'travel_group_id', 'travel_group_binding'):
            if key in item:
                request[key] = item[key]
        requests.append(request)
    return requests


def normalize_email_grouping(value: Any = "individual") -> str:
    if value not in ("individual", "source"):
        raise IntakeError("email_grouping must be individual or source.")
    return value


def source_email_group_plan(intakes: list[dict[str, Any]], recipients: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Only an explicit source hash establishes email membership; empty hashes never merge."""
    if len(intakes) != len(recipients):
        raise IntakeError("Source email group recipient count does not match the requests.")
    groups: list[dict[str, Any]] = []
    by_source: dict[str, dict[str, Any]] = {}
    for index, (intake, contact) in enumerate(zip(intakes, recipients)):
        source = str(intake.get("source_sha256") or "").strip()
        recipient = str(contact.get("recipient") or "").strip().lower()
        profile = str(intake.get("personal_profile_id") or "").strip()
        if not recipient:
            raise IntakeError("Every source email group member needs a validated recipient.")
        group = by_source.get(source) if source else None
        if group and (group["recipient"] != recipient or group["personal_profile_id"] != profile):
            raise IntakeError("Requests from the same source photo have different recipients or personal profiles. Align the selections or choose individual emails.")
        if group is None:
            group = {"source_sha256": source, "recipient": recipient, "personal_profile_id": profile,
                     "member_indices": []}
            groups.append(group)
            if source:
                by_source[source] = group
        group["member_indices"].append(index)
    for group in groups:
        members = [intakes[index] for index in group["member_indices"]]
        if len(members) > 1:
            source_email_body(members, signature_name="")  # Validate custom-body handling before any writes.
        group["group_id"] = "source-email-" + stable_json_hash({**group, "requests": [_intake_identity_payload(row) for row in members]})[:24]
    return groups


def build_source_email_groups(*, plans: list[dict[str, Any]], intakes: list[dict[str, Any]],
                             items: list[dict[str, Any]], profiles: list[dict[str, Any]], paths: AppPaths) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for plan in plans:
        indices = plan["member_indices"]
        selected_items = [items[index] for index in indices]
        child_payloads = [load_json(Path(item["draft_payload"])) for item in selected_items]
        children: list[dict[str, Any]] = []
        attachments: list[str] = []
        for index, item, child_payload in zip(indices, selected_items, child_payloads):
            errors = validate_draft_payload(child_payload)
            if errors:
                raise IntakeError("A source email group child is blocked: " + "; ".join(errors))
            child = {key: child_payload.get(key, '') for key in ('case_number', 'service_date', 'service_period_label', 'service_start_time', 'service_end_time')}
            child.update({key: child_payload[key] for key in ('claim_interpreting', 'claim_transport', 'travel_group_id', 'travel_group_binding') if key in child_payload})
            child.update(source_sha256=plan["source_sha256"], personal_profile_id=plan["personal_profile_id"],
                         recipient=plan["recipient"], pdf=str(Path(item["pdf"]).resolve()),
                         pdf_sha256=file_sha256(Path(item["pdf"])), draft_payload=str(Path(item["draft_payload"]).resolve()),
                         draft_payload_sha256=file_sha256(Path(item["draft_payload"])))
            children.append(child)
            for attachment in child_payload["attachment_files"]:
                if attachment not in attachments:
                    attachments.append(attachment)
        payload = copy.deepcopy(child_payloads[0])
        # Claims live on each request; a group must never masquerade as one shared-trip owner.
        for key in ('claim_interpreting', 'claim_transport', 'travel_group_id', 'travel_group_binding'):
            payload.pop(key, None)
        if len(indices) > 1:
            signature = build_rendered_request(intakes[indices[0]], profiles[indices[0]]).signature_name
            payload['body'] = source_email_body([intakes[index] for index in indices], signature_name=signature)
            payload['subject'] = ('Requerimentos de honorários' if any(intakes[index].get('claim_interpreting', True) for index in indices)
                                  else 'Requerimentos de despesas de transporte')
        payload.update(email_grouping='source', email_group_id=plan['group_id'], source_sha256=plan['source_sha256'],
                       personal_profile_id=plan['personal_profile_id'], member_indices=indices,
                       underlying_requests=children, child_payload_paths=[child['draft_payload'] for child in children],
                       attachment_files=attachments, attachment_file_list=attachments,
                       attachment_basenames=[Path(path).name for path in attachments],
                       attachment_sha256={path: file_sha256(Path(path)) for path in attachments},
                       additional_attachment_files=[path for path in attachments if path not in {child['pdf'] for child in children}])
        payload['gmail_create_draft_args'] = {"to": payload['to'], "subject": payload['subject'], "body": payload['body'], "attachment_files": attachments}
        errors = validate_draft_payload(payload)
        if errors:
            raise IntakeError("Source email group is blocked: " + "; ".join(errors))
        payload_path = paths.draft_output_dir / f"{plan['group_id']}-{secrets.token_hex(4)}.draft.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        groups.append({**copy.deepcopy(plan), 'email_grouping': 'source', 'case_number': payload['case_number'],
                       'service_date': payload['service_date'], 'service_period_label': payload['service_period_label'],
                       'underlying_requests': children, 'child_payload_paths': payload['child_payload_paths'],
                       'attachment_files': attachments, 'attachment_count': len(attachments),
                       'attachment_sha256': payload['attachment_sha256'], 'pdf': children[0]['pdf'],
                       'draft_payload': str(payload_path.resolve()), 'payload_path': str(payload_path.resolve()),
                       'gmail_tool': '_create_draft', 'gmail_create_draft_args': payload['gmail_create_draft_args'],
                       'subject': payload['subject'], 'body': payload['body'], 'draft_only': True, 'send_allowed': False,
                       'gmail_create_draft_ready': True, 'gmail_create_draft_blocker': ''})
    return groups


def default_packet_email_body(items: list[dict[str, Any]], email_config: dict[str, Any], *, signature_name: str = "") -> str:
    default_body = resolve_email_body({}, email_config, signature_name=signature_name)
    signature = "Example Interpreter"
    if "Melhores cumprimentos," in default_body:
        signature = default_body.split("Melhores cumprimentos,", 1)[1].strip() or signature
    count = len(items)
    request_word = "requerimento" if count == 1 else "requerimentos"
    fee_claim = any(item.get('claim_interpreting', True) for item in items)
    travel_claim = any(item.get('claim_transport', False) for item in items)
    scope = ('honorários e despesas de transporte' if travel_claim else 'honorários') if fee_claim else 'despesas de transporte'
    return (
        "Bom dia,\n\n"
        f"Venho por este meio requerer o pagamento de {scope}, conforme os pedidos individuais anexos.\n\n"
        f"Poderão encontrar em anexo um pacote PDF com {count} {request_word}.\n\n"
        "Melhores cumprimentos,\n\n"
        f"{signature}"
    )


def validate_packet_recipients(intakes: list[dict[str, Any]], email_config: dict[str, Any], court_directory: list[dict[str, Any]]) -> str:
    custom_body = str(intakes[0].get('packet_email_body') or '')
    if custom_body.strip():
        resolve_email_body({'claim_interpreting': any(intake.get('claim_interpreting', True) for intake in intakes),
                            'claim_transport': any(intake.get('claim_transport', False) for intake in intakes),
                            'email_body': custom_body}, email_config)
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
    signature_name: str = "",
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
    packet_intake['claim_interpreting'] = any(item.get('claim_interpreting', True) for item in items)
    packet_intake['claim_transport'] = any(item.get('claim_transport', False) for item in items)
    packet_intake.pop('travel_group_id', None)
    packet_intake.pop('travel_group_binding', None)
    packet_intake["service_period_label"] = "packet"
    packet_intake.pop("additional_attachment_files", None)
    packet_intake["underlying_requests"] = underlying_requests_for_packet(items)
    custom_packet_body = str(packet_intake.get("packet_email_body") or "")
    packet_intake["email_body"] = custom_packet_body if custom_packet_body.strip() else default_packet_email_body(items, email_config, signature_name=signature_name)

    payload = build_email_payload(packet_intake, packet_pdf, email_config, court_directory, signature_name=signature_name)
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


def preflight_next_safe_action(status: str, *, packet_mode: bool = False) -> dict[str, Any]:
    if status == "ready":
        mode = "packet PDF" if packet_mode else "batch package"
        return next_safe_action(
            state="prepare_batch",
            title="Batch preflight clear",
            detail=f"No files were created. Review the queued requests, then prepare the {mode} when ready.",
            button_id="prepare-batch-intakes",
            blocked=False,
        )
    return next_safe_action(
        state="fix_batch_blockers",
        title="Fix batch blockers before preparing",
        detail="The batch has duplicate, recipient, active-draft, or intake blockers. No PDF or draft payload was created.",
        button_id="",
        blocked=True,
    )


def preflight_item_summary(
    *,
    index: int,
    intake: dict[str, Any],
    status: str,
    message: str,
    key: tuple[str, str, str] | None = None,
    recipient: str = "",
    recipient_source: str = "",
    lifecycle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case_number = key[0] if key else normalize_case_number(str(intake.get("case_number") or ""))
    service_date = key[1] if key else str(intake.get("service_date") or intake.get("photo_metadata_date") or "")
    period = key[2] if key else str(intake.get("service_period_label") or "").strip()
    transport = intake.get("transport") if isinstance(intake.get("transport"), dict) else {}
    attachments = intake.get("additional_attachment_files") if isinstance(intake.get("additional_attachment_files"), list) else []
    summary = {
        "index": index,
        "status": status,
        "message": message,
        "case_number": case_number,
        "raw_case_number": str(intake.get("raw_case_number") or intake.get("source_case_number") or ""),
        "service_date": service_date,
        "service_date_source": str(intake.get("service_date_source") or ""),
        "photo_metadata_date": str(intake.get("photo_metadata_date") or ""),
        "source_document_timestamp": str(intake.get("source_document_timestamp") or ""),
        "service_period_label": period,
        "service_start_time": str(intake.get("service_start_time") or ""),
        "service_end_time": str(intake.get("service_end_time") or ""),
        "payment_entity": str(intake.get("payment_entity") or ""),
        "service_entity": str(intake.get("service_entity") or ""),
        "service_place": str(intake.get("service_place") or ""),
        "recipient": recipient,
        "recipient_source": recipient_source,
        "transport_destination": str(transport.get("destination") or intake.get("transport_destination") or ""),
        "km_one_way": str(transport.get("km_one_way") or intake.get("km_one_way") or ""),
        "source_filename": str(intake.get("source_filename") or ""),
        "additional_attachment_count": len(attachments),
        "draft_lifecycle": lifecycle or {},
        "send_allowed": False,
        "write_allowed": False,
    }
    summary.update({key: intake.get(key, default) for key, default in (('claim_interpreting', True), ('claim_transport', False))})
    if 'travel_group_id' in intake:
        summary['travel_group_id'] = intake['travel_group_id']
    if key:
        summary.update(claim_metadata(intake))
        summary["duplicate_key"] = {
            "case_number": key[0],
            "service_date": key[1],
            "service_period_label": key[2],
        }
    return summary


def recorded_claims(paths: AppPaths) -> list[dict[str, Any]]:
    return recorded_travel_requests(load_draft_log(paths.draft_log), read_json_list(paths.duplicate_index))


def preflight_intakes(
    intakes: list[dict[str, Any]],
    paths: AppPaths,
    *,
    allow_duplicate: bool = False,
    allow_existing_draft: bool = False,
    correction_reason: str = "",
    packet_mode: bool = False,
    email_grouping: str = "individual",
) -> dict[str, Any]:
    if not intakes:
        raise IntakeError("At least one intake is required.")
    email_grouping = normalize_email_grouping(email_grouping)

    normalized_correction_reason = str(correction_reason or "").strip()
    correction_mode = bool(normalized_correction_reason)
    effective_records = [effective_intake_for_profile(intake, paths) for intake in intakes]
    effective_intakes = [record[0] for record in effective_records]
    generator_profiles = [record[1] for record in effective_records]
    email_config = load_json(paths.email_config)
    court_directory = read_json_list(paths.court_emails)
    draft_log = load_draft_log(paths.draft_log)
    intake_paths = planned_intake_paths(effective_intakes, paths)
    effective_allow_duplicate = bool(allow_duplicate or correction_mode)
    effective_allow_existing_draft = bool(allow_existing_draft or correction_mode)

    items: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    seen_keys: dict[tuple[str, str, str], str] = {}
    group_error = ''
    try:
        validate_shared_travel_groups(effective_intakes, prior_requests=recorded_claims(paths))
        if correction_mode:
            lifecycles = [draft_lifecycle_for_intake(intake, paths) for intake in effective_intakes]
            if any(check['status'] != 'clear' and not check['replacement_allowed'] for check in lifecycles):
                raise IntakeError('Correction mode cannot replace sent or non-replaceable requests.')
            if not any(check['replacement_allowed'] for check in lifecycles):
                raise IntakeError('Correction mode requires an existing active/drafted request in the reviewed batch.')
            ids = sorted({draft_id for check in lifecycles for draft_id in _lifecycle_blocking_draft_ids(check)})
            validate_superseded_request_coverage(effective_intakes, draft_log, ids)
    except (ClaimError, IntakeError, ValueError) as exc:
        group_error = str(exc)

    for index, (intake_path, intake, generator_profile) in enumerate(zip(intake_paths, effective_intakes, generator_profiles), start=1):
        lifecycle = draft_lifecycle_for_intake(intake, paths)
        try:
            if group_error:
                raise IntakeError(group_error)
            key = validate_intake_before_generation(
                intake_path,
                intake,
                profile=generator_profile,
                email_config=email_config,
                court_directory=court_directory,
                duplicate_index=paths.duplicate_index,
                draft_log=draft_log,
                allow_duplicate=effective_allow_duplicate,
                allow_existing_draft=effective_allow_existing_draft,
                correction_reason=normalized_correction_reason,
            )
            if key in seen_keys:
                raise IntakeError(f"Duplicate request appears more than once in this batch: item {index} duplicates {seen_keys[key]}")
            seen_keys[key] = f"item {index}"
            recipient, recipient_source = resolve_recipient(intake, email_config, court_directory)
            items.append(preflight_item_summary(
                index=index,
                intake=intake,
                status="ready",
                message="Ready for artifact preparation.",
                key=key,
                recipient=recipient,
                recipient_source=recipient_source,
                lifecycle=lifecycle,
            ))
        except (IntakeError, OSError, ValueError) as exc:
            message = str(exc)
            blocker = {
                "index": index,
                "message": message,
                "send_allowed": False,
                "write_allowed": False,
            }
            blockers.append(blocker)
            items.append(preflight_item_summary(
                index=index,
                intake=intake,
                status="blocked",
                message=message,
                lifecycle=lifecycle,
            ))

    packet: dict[str, Any] | None = None
    email_groups: list[dict[str, Any]] = []
    if email_grouping == "source" and not packet_mode and not blockers:
        try:
            email_groups = source_email_group_plan(effective_intakes, [{"recipient": item["recipient"]} for item in items])
        except IntakeError as exc:
            blockers.append({"index": None, "message": str(exc), "send_allowed": False, "write_allowed": False})
    if packet_mode and not blockers:
        try:
            recipient = validate_packet_recipients(effective_intakes, email_config, court_directory)
            packet = {
                "status": "ready",
                "recipient": recipient,
                "request_count": len(intakes),
                "message": "Packet mode is valid. All queued requests resolve to the same recipient.",
                "send_allowed": False,
                "write_allowed": False,
            }
        except IntakeError as exc:
            message = str(exc)
            blockers.append({
                "index": None,
                "message": message,
                "send_allowed": False,
                "write_allowed": False,
            })
            packet = {
                "status": "blocked",
                "message": message,
                "send_allowed": False,
                "write_allowed": False,
            }

    status = "blocked" if blockers else "ready"
    if blockers:
        message = "Batch preflight blocked: " + " | ".join(blocker["message"] for blocker in blockers)
    else:
        mode = "packet PDF" if packet_mode else "separate PDF/draft payloads"
        message = f"Batch preflight clear for {len(intakes)} request(s). No files were created. Next step: prepare {mode}."

    result = {
        "status": status,
        "message": message,
        "artifact_effect": "none",
        "write_allowed": False,
        "send_allowed": False,
        "packet_mode": bool(packet_mode),
        "email_grouping": email_grouping,
        "email_groups": email_groups,
        "correction_mode": correction_mode,
        "correction_reason": normalized_correction_reason,
        "items": items,
        "blockers": blockers,
        "packet": packet,
        "next_safe_action": preflight_next_safe_action(status, packet_mode=bool(packet_mode)),
    }
    if status == "ready":
        recipients = [
            {
                "recipient": str(item.get("recipient") or ""),
                "recipient_source": str(item.get("recipient_source") or ""),
            }
            for item in items
        ]
        result["preflight_review"] = _build_preflight_review(
            effective_intakes=effective_intakes,
            recipients=recipients,
            packet_mode=bool(packet_mode),
            correction_mode=correction_mode,
            correction_reason=normalized_correction_reason,
            email_grouping=email_grouping,
        )
    return result


def prepare_intakes(
    intakes: list[dict[str, Any]],
    paths: AppPaths,
    *,
    render_previews: bool = False,
    allow_duplicate: bool = False,
    allow_existing_draft: bool = False,
    correction_reason: str = "",
    packet_mode: bool = False,
    email_grouping: str = "individual",
) -> dict[str, Any]:
    if not intakes:
        raise IntakeError("At least one intake is required.")
    email_grouping = normalize_email_grouping(email_grouping)

    normalized_correction_reason = str(correction_reason or "").strip()
    correction_mode = bool(normalized_correction_reason)
    effective_records = [effective_intake_for_profile(intake, paths) for intake in intakes]
    effective_intakes = [record[0] for record in effective_records]
    generator_profiles = [record[1] for record in effective_records]
    email_config = load_json(paths.email_config)
    court_directory = read_json_list(paths.court_emails)
    draft_log = load_draft_log(paths.draft_log)
    intake_paths = planned_intake_paths(effective_intakes, paths)
    seen_keys: dict[tuple[str, str, str], Path] = {}
    lifecycle_checks: list[dict[str, Any]] = []
    try:
        validate_shared_travel_groups(effective_intakes, prior_requests=recorded_claims(paths))
    except ClaimError as exc:
        raise IntakeError(str(exc)) from exc

    if correction_mode:
        for intake in effective_intakes:
            lifecycle = draft_lifecycle_for_intake(intake, paths)
            lifecycle_checks.append(lifecycle)
            if not lifecycle["replacement_allowed"] and lifecycle['status'] != 'clear':
                raise IntakeError(
                    "Correction mode requires an existing active/drafted request for the same case/date/period, "
                    f"and cannot replace sent requests. {lifecycle['message']}"
                )
        if not any(lifecycle['replacement_allowed'] for lifecycle in lifecycle_checks):
            raise IntakeError('Correction mode requires an existing active/drafted request in the reviewed batch.')
        blocking_ids = sorted({draft_id for lifecycle in lifecycle_checks for draft_id in _lifecycle_blocking_draft_ids(lifecycle)})
        try:
            validate_superseded_request_coverage(effective_intakes, draft_log, blocking_ids)
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc

    effective_allow_duplicate = bool(allow_duplicate or correction_mode)
    effective_allow_existing_draft = bool(allow_existing_draft or correction_mode)

    for intake_path, intake, generator_profile in zip(intake_paths, effective_intakes, generator_profiles):
        key = validate_intake_before_generation(
            intake_path,
            intake,
            profile=generator_profile,
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
        validate_packet_recipients(effective_intakes, email_config, court_directory)

    email_group_plans = []
    if email_grouping == "source" and not packet_mode:
        contacts = [{"recipient": resolve_recipient(intake, email_config, court_directory)[0]} for intake in effective_intakes]
        email_group_plans = source_email_group_plan(effective_intakes, contacts)

    write_intake_files(effective_intakes, intake_paths)

    effective_render_previews = render_previews
    preview_warning = ""
    if render_previews and not shutil.which("pdftoppm"):
        effective_render_previews = False
        preview_warning = "pdftoppm is not available; PDF generated without PNG preview."

    items = []
    for intake_path, generator_profile in zip(intake_paths, generator_profiles):
        items.append(
            prepare_one(
                intake_path,
                profile=generator_profile,
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
        )
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
            intakes=effective_intakes,
            items=items,
            paths=paths,
            email_config=email_config,
            court_directory=court_directory,
            render_previews=effective_render_previews,
            preview_warning=preview_warning,
            signature_name=build_rendered_request(effective_intakes[0], generator_profiles[0]).signature_name,
        )
    email_groups = build_source_email_groups(plans=email_group_plans, intakes=effective_intakes, items=items,
                                            profiles=generator_profiles, paths=paths) if email_group_plans else []
    paths.manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = paths.manifest_dir / f"web-prepared-{timestamp_slug()}-{secrets.token_hex(8)}.json"
    gmail_status = gmail_api_status(paths)
    prepared_review_material = _prepared_review_material(
        effective_intakes=effective_intakes,
        items=items,
        packet=packet,
        manifest_path=manifest_path,
        packet_mode=bool(packet_mode),
        correction_mode=correction_mode,
        correction_reason=normalized_correction_reason,
        email_grouping=email_grouping,
        email_groups=email_groups,
    )
    prepared_review = _prepared_review_from_material(prepared_review_material)
    manifest = {
        "status": "prepared",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "draft_creation_tool": "_create_draft",
        "send_allowed": False,
        "correction_mode": correction_mode,
        "correction_reason": normalized_correction_reason,
        "packet_mode": bool(packet_mode),
        "email_grouping": email_grouping,
        "email_groups": email_groups,
        "next_safe_action": prepared_next_safe_action(packet_mode=bool(packet_mode), gmail_status=gmail_status),
        "prepared_review": prepared_review,
        "prepared_review_material": prepared_review_material,
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
    notes = str(payload.get("correction_reason") or payload.get("reason") or payload.get("notes") or "").strip()
    if notes:
        args.extend(["--notes", notes])

    stdout = StringIO()
    stderr = StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = record_gmail_draft_main(args)
    if code != 0:
        detail = stderr.getvalue().strip()
        message = "Could not record Gmail draft. Check payload path and draft/message IDs."
        if detail:
            message = f"{message} {detail}"
        raise IntakeError(message)


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


def record_draft(
    payload: dict[str, Any],
    paths: AppPaths,
    *,
    require_handoff_reviewed_for_prepared_payload: bool = False,
    _trusted_prepared_recovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload_path = str(payload.get("payload") or "").strip()
    status = str(payload.get("status") or "active").strip()
    existing_sent_transition = status == 'sent' and any(row.get('draft_id') == payload.get('draft_id') for row in load_draft_log(paths.draft_log))
    if not payload_path and status in {'active', 'drafted', 'sent'} and payload.get('draft_payload'):
        alias = _resolve_optional_path(payload['draft_payload'])
        if alias.is_file():
            alias_data = load_json(alias)
            if alias_data.get('email_grouping') == 'source':
                # The compatibility alias must not bypass source-group review signing.
                payload = {**payload, 'payload': str(alias)}
                payload_path = str(alias)
    if payload_path and (status in {"active", "drafted"} or (status == 'sent' and not existing_sent_transition and _load_draft_payload_for_response(payload).get('email_grouping') == 'source')):
        review = (_trusted_prepared_recovery if _trusted_prepared_recovery is not None
                  else require_current_prepared_review(payload, payload_path, paths))
        if require_handoff_reviewed_for_prepared_payload and not bool(payload.get("gmail_handoff_reviewed")):
            raise IntakeError("Review the PDF preview and exact Gmail draft args before local recording.")
        _, draft_data = _load_prepared_draft_payload(payload_path)
        if draft_data.get('email_grouping') == 'source':
            superseded = _coerce_supersedes(payload.get('supersedes'))
            if superseded and not review.get('correction_mode'):
                raise IntakeError('Group replacement requires a prepared review created in correction mode.')
            reason = _gmail_correction_reason(payload) or str(review.get('correction_reason') or '')
            if review.get('correction_reason') and reason != review['correction_reason']:
                raise IntakeError('Correction reason does not match the prepared review.')
            try:
                validate_source_group_history(draft_data, load_draft_log(paths.draft_log), read_json_list(paths.duplicate_index),
                                              draft_id=str(payload.get('draft_id') or ''), supersedes=superseded, reason=reason, status=status)
            except ValueError as exc:
                raise IntakeError(str(exc)) from exc

    supersedes = _coerce_supersedes(payload.get("supersedes"))
    supersede_records: list[tuple[str, dict[str, Any]]] = []
    if supersedes:
        draft_log = load_draft_log(paths.draft_log)
        existing_by_id = {str(record.get("draft_id") or "").strip(): record for record in draft_log}
        for old_draft_id in supersedes:
            old_record = existing_by_id.get(old_draft_id)
            if not old_record:
                raise IntakeError(f"Cannot supersede unknown draft ID: {old_draft_id}")
            supersede_records.append((old_draft_id, old_record))

        loaded_for_coverage = _load_draft_payload_for_response(payload)
        try:
            validate_superseded_request_coverage(_prepared_payload_request_identities(loaded_for_coverage or payload), draft_log, supersedes)
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc

    _record_draft_once(payload, paths)
    superseded_drafts: list[str] = []
    for old_draft_id, old_record in supersede_records:
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
