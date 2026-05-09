from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import secrets
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx

from scripts.build_email_draft import validate_draft_payload
from scripts.generate_pdf import IntakeError


GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_DRAFTS_CREATE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
GMAIL_DRAFT_GET_URL_TEMPLATE = "https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}"
FAKE_GMAIL_DRAFT_API_ENV = "HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"
DEFAULT_GMAIL_REDIRECT_URI = "http://127.0.0.1:8766/api/gmail/oauth/callback"
DEFAULT_GMAIL_TOKEN_PATH = "config/gmail-token.local.json"
SAFE_GMAIL_CONFIG_LABEL = "config/gmail.local.json"
SAFE_GMAIL_EXAMPLE_LABEL = "config/gmail.example.json"


def fake_gmail_draft_api_enabled() -> bool:
    return str(os.environ.get(FAKE_GMAIL_DRAFT_API_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def gmail_draft_get_url(draft_id: str) -> str:
    return GMAIL_DRAFT_GET_URL_TEMPLATE.format(draft_id=quote(str(draft_id), safe=""))


def _read_json_object_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_relative_label(path: Path, *, root: Path | None = None) -> str:
    base = root or path.parent.parent
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


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
        return config_value, "config/gmail.local.json"
    return "", ""


def gmail_config(config_path: Path) -> dict[str, Any]:
    config = _read_json_object_if_exists(config_path)
    client_id, client_id_source = _configured_value_and_source(
        config,
        "GMAIL_CLIENT_ID",
        "client_id",
        config_path,
    )
    client_secret, client_secret_source = _configured_value_and_source(
        config,
        "GMAIL_CLIENT_SECRET",
        "client_secret",
        config_path,
    )
    token_path_text, token_path_source = _configured_value_and_source(
        config,
        "GMAIL_TOKEN_PATH",
        "token_path",
        config_path,
    )
    redirect_uri, redirect_uri_source = _configured_value_and_source(
        config,
        "GMAIL_REDIRECT_URI",
        "redirect_uri",
        config_path,
    )
    if token_path_text:
        token_path = Path(token_path_text).expanduser()
        if not token_path.is_absolute():
            token_path = config_path.parent.parent / token_path
    else:
        token_path = config_path.with_name("gmail-token.local.json")
    return {
        "client_id": client_id,
        "client_id_source": client_id_source,
        "client_secret": client_secret,
        "client_secret_source": client_secret_source,
        "token_path": token_path,
        "token_path_source": token_path_source or "default_local",
        "redirect_uri": redirect_uri or DEFAULT_GMAIL_REDIRECT_URI,
        "redirect_uri_source": redirect_uri_source or "default_local",
    }


def gmail_setup_payload(
    *,
    config_path: Path,
    config: dict[str, Any],
    configured: bool,
    connected: bool,
    token_store_present: bool,
) -> dict[str, Any]:
    if connected:
        next_step = "Gmail is connected. Review a PDF preview and exact draft args before optional in-app draft creation; Manual Draft Handoff remains available as a safe fallback."
        checklist_status = "ready"
    elif configured:
        next_step = "Manual Draft Handoff is ready now. Connect Gmail API only if you want optional in-app draft creation."
        checklist_status = "manual_handoff"
    else:
        next_step = "Manual Draft Handoff is ready now. OAuth setup can be added from the optional Gmail Draft API panel."
        checklist_status = "manual_handoff"
    return {
        "status": checklist_status,
        "next_step": next_step,
        "config_path": SAFE_GMAIL_CONFIG_LABEL,
        "example_config_path": SAFE_GMAIL_EXAMPLE_LABEL,
        "redirect_uri": config["redirect_uri"],
        "redirect_uri_source": config["redirect_uri_source"],
        "token_path": _safe_relative_label(config["token_path"], root=config_path.parent.parent),
        "token_path_source": config["token_path_source"],
        "config_file_present": config_path.exists(),
        "token_store_present": token_store_present,
        "client_id_configured": bool(config["client_id"]),
        "client_secret_configured": bool(config["client_secret"]),
        "manual_handoff_ready": True,
        "recommended_mode": "gmail_api" if connected else "manual_handoff",
        "draft_only": True,
        "send_allowed": False,
        "steps": [
            {
                "label": "Manual Draft Handoff",
                "done": True,
                "description": "Prepare the PDF and exact draft args, create the draft through the manual connector handoff, then record returned IDs locally.",
            },
            {
                "label": "Save OAuth client",
                "done": configured,
                "description": "Use a Google OAuth desktop client. The secret is written only to ignored local config.",
            },
            {
                "label": "Connect Gmail",
                "done": connected,
                "description": "Authorize the narrow Gmail compose scope, then return to this app.",
            },
            {
                "label": "Create reviewed draft",
                "done": False,
                "description": "Available only after PDF preview, exact draft args, and duplicate checks pass.",
            },
        ],
    }


def _validate_gmail_redirect_uri(redirect_uri: str) -> str:
    value = redirect_uri.strip() or DEFAULT_GMAIL_REDIRECT_URI
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise IntakeError("Gmail redirect URI must be a local loopback URL such as http://127.0.0.1:8766/api/gmail/oauth/callback.")
    if parsed.path != "/api/gmail/oauth/callback":
        raise IntakeError("Gmail redirect URI must end with /api/gmail/oauth/callback.")
    return value


def save_gmail_local_config(payload: dict[str, Any], config_path: Path) -> dict[str, Any]:
    client_id = str(payload.get("client_id") or "").strip()
    client_secret = str(payload.get("client_secret") or "").strip()
    redirect_uri = _validate_gmail_redirect_uri(str(payload.get("redirect_uri") or DEFAULT_GMAIL_REDIRECT_URI))
    token_path = str(payload.get("token_path") or DEFAULT_GMAIL_TOKEN_PATH).strip() or DEFAULT_GMAIL_TOKEN_PATH

    if not client_id:
        raise IntakeError("Gmail OAuth client ID is required.")
    if ".apps.googleusercontent.com" not in client_id:
        raise IntakeError("Gmail OAuth client ID should look like a Google desktop OAuth client ending in .apps.googleusercontent.com.")
    if not client_secret:
        raise IntakeError("Gmail OAuth client secret is required.")
    if Path(token_path).is_absolute():
        raise IntakeError("Gmail token path must stay relative to this project, for example config/gmail-token.local.json.")
    if ".." in Path(token_path).parts:
        raise IntakeError("Gmail token path must not contain parent-directory segments.")

    existing = _read_json_object_if_exists(config_path)
    backup_label = ""
    if existing:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = config_path.with_name(f"gmail.backup-{timestamp}.local.json")
        _write_json_object(backup_path, existing)
        backup_label = _safe_relative_label(backup_path, root=config_path.parent.parent)

    _write_json_object(config_path, {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "token_path": token_path,
    })
    status = gmail_status_payload(config_path)
    return {
        "status": "saved",
        "message": "Gmail OAuth config saved locally. Client secret was not returned; Manual Draft Handoff remains ready while you choose whether to use optional Gmail API drafting.",
        "gmail": status,
        "setup": status.get("setup", {}),
        "config_path": SAFE_GMAIL_CONFIG_LABEL,
        "backup_path": backup_label,
        "draft_only": True,
        "send_allowed": False,
    }


def read_gmail_token(token_path: Path) -> dict[str, Any]:
    return _read_json_object_if_exists(token_path)


def write_gmail_token(token_path: Path, token: dict[str, Any]) -> None:
    _write_json_object(token_path, token)


def _google_error_message(response: httpx.Response | None, fallback: str) -> str:
    if response is None:
        return fallback
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        error = payload.get("error")
        description = payload.get("error_description")
        message = payload.get("message")
        parts = [str(item).strip() for item in (error, description, message) if str(item or "").strip()]
        if parts:
            return " - ".join(parts)
    text = str(response.text or "").strip()
    return text[:240] if text else fallback


def token_expired(token: dict[str, Any]) -> bool:
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


def exchange_google_token(form: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        try:
            response = client.post(GOOGLE_OAUTH_TOKEN_URL, data=form)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _google_error_message(exc.response, "Google rejected the OAuth token exchange.")
            raise IntakeError(f"Google OAuth token exchange failed: {detail}") from exc
        except httpx.RequestError as exc:
            raise IntakeError("Google OAuth token exchange failed because the network request did not complete.") from exc
        payload = response.json()
    output = dict(payload)
    expires_in = int(output.get("expires_in") or 0)
    if expires_in:
        output["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    return output


def gmail_status_payload(config_path: Path) -> dict[str, Any]:
    if fake_gmail_draft_api_enabled():
        return {
            "provider": "gmail_api",
            "scope": GMAIL_COMPOSE_SCOPE,
            "configured": True,
            "connected": True,
            "draft_create_ready": True,
            "manual_handoff_ready": True,
            "recommended_mode": "gmail_api",
            "fake_mode": True,
            "client_id_source": "synthetic_smoke_env",
            "client_secret_configured": False,
            "client_secret_source": "",
            "redirect_uri_source": "synthetic_smoke_env",
            "token_store_configured": False,
            "token_store_present": False,
            "access_token_present": False,
            "refresh_token_present": False,
            "token_path_source": "",
            "gmail_api_action": "users.drafts.create",
            "gmail_readonly_verify_action": "users.drafts.get",
            "draft_only": True,
            "send_allowed": False,
            "setup": {
                "status": "ready",
                "next_step": "Synthetic smoke mode is ready. No Google network call will be made. Manual Draft Handoff remains available as a safe fallback.",
                "config_path": SAFE_GMAIL_CONFIG_LABEL,
                "example_config_path": SAFE_GMAIL_EXAMPLE_LABEL,
                "redirect_uri": DEFAULT_GMAIL_REDIRECT_URI,
                "token_path": DEFAULT_GMAIL_TOKEN_PATH,
                "manual_handoff_ready": True,
                "recommended_mode": "gmail_api",
                "draft_only": True,
                "send_allowed": False,
            },
            "message": "Synthetic Gmail Draft API smoke mode is enabled. No Google network call will be made. Manual Draft Handoff remains available as a safe fallback.",
        }
    config = gmail_config(config_path)
    token_store_present = False
    access_token_present = False
    refresh_token_present = False
    try:
        token_store_present = config["token_path"].exists()
        token = read_gmail_token(config["token_path"])
        access_token_present = bool(token.get("access_token"))
        refresh_token_present = bool(token.get("refresh_token"))
    except OSError:
        token_store_present = False
    configured = bool(config["client_id"] and config["client_secret"])
    connected = bool(configured and token_store_present and (access_token_present or refresh_token_present))
    recommended_mode = "gmail_api" if connected else "manual_handoff"
    setup = gmail_setup_payload(
        config_path=config_path,
        config=config,
        configured=configured,
        connected=connected,
        token_store_present=token_store_present,
    )
    return {
        "provider": "gmail_api",
        "scope": GMAIL_COMPOSE_SCOPE,
        "configured": configured,
        "connected": connected,
        "draft_create_ready": connected,
        "manual_handoff_ready": True,
        "recommended_mode": recommended_mode,
        "client_id_source": config["client_id_source"],
        "client_secret_configured": bool(config["client_secret"]),
        "client_secret_source": config["client_secret_source"],
        "redirect_uri_source": config["redirect_uri_source"],
        "token_store_configured": True,
        "token_store_present": token_store_present,
        "access_token_present": access_token_present,
        "refresh_token_present": refresh_token_present,
        "token_path_source": config["token_path_source"],
        "gmail_api_action": "users.drafts.create",
        "gmail_readonly_verify_action": "users.drafts.get",
        "draft_only": True,
        "send_allowed": False,
        "setup": setup,
        "message": (
            "Gmail Draft API is connected. The app can create reviewed drafts only; Manual Draft Handoff remains available as a safe fallback."
            if connected
            else "Manual Draft Handoff is ready. Gmail API OAuth is disconnected and optional direct draft creation can be connected later."
        ),
    }


def gmail_oauth_start(config_path: Path) -> dict[str, Any]:
    config = gmail_config(config_path)
    if not config["client_id"] or not config["client_secret"]:
        raise IntakeError("Gmail OAuth needs GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET or config/gmail.local.json.")
    state = secrets.token_urlsafe(24)
    token = read_gmail_token(config["token_path"])
    token.update({
        "oauth_state": state,
        "oauth_started_at": datetime.now(timezone.utc).isoformat(),
        "scope": GMAIL_COMPOSE_SCOPE,
    })
    write_gmail_token(config["token_path"], token)
    query = urlencode({
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": GMAIL_COMPOSE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return {
        "status": "authorization_ready",
        "authorization_url": f"{GOOGLE_OAUTH_AUTH_URL}?{query}",
        "state": state,
        "scope": GMAIL_COMPOSE_SCOPE,
        "redirect_uri_source": config["redirect_uri_source"],
        "gmail_api_action": "users.drafts.create",
        "draft_only": True,
        "send_allowed": False,
    }


def gmail_oauth_callback(*, code: str, state: str, config_path: Path) -> dict[str, Any]:
    config = gmail_config(config_path)
    token = read_gmail_token(config["token_path"])
    expected_state = str(token.get("oauth_state") or "").strip()
    if not expected_state or state != expected_state:
        raise IntakeError("Gmail OAuth state mismatch. Start the OAuth flow again.")
    if not code:
        raise IntakeError("Gmail OAuth callback is missing an authorization code.")
    exchanged = exchange_google_token({
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
        "scope": exchanged.get("scope") or GMAIL_COMPOSE_SCOPE,
    }
    write_gmail_token(config["token_path"], stored)
    return {
        "status": "connected",
        "provider": "gmail_api",
        "connected": True,
        "scope": stored["scope"],
        "token_store_present": True,
        "gmail_api_action": "users.drafts.create",
        "draft_only": True,
        "send_allowed": False,
    }


def gmail_access_token(config_path: Path) -> tuple[str, dict[str, Any]]:
    config = gmail_config(config_path)
    token = read_gmail_token(config["token_path"])
    access_token = str(token.get("access_token") or "").strip()
    if access_token and not token_expired(token):
        return access_token, token
    refresh_token = str(token.get("refresh_token") or "").strip()
    if refresh_token and config["client_id"] and config["client_secret"]:
        refreshed = exchange_google_token({
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        token.update(refreshed)
        if "refresh_token" not in token:
            token["refresh_token"] = refresh_token
        write_gmail_token(config["token_path"], token)
        access_token = str(token.get("access_token") or "").strip()
        if access_token:
            return access_token, token
    raise IntakeError("Gmail Draft API is not connected. Use Manual Draft Handoff now, or connect Gmail OAuth later.")


def _attachment_bytes(path: Path) -> tuple[bytes, str, str]:
    content_type, _encoding = mimetypes.guess_type(path.name)
    if not content_type:
        content_type = "application/octet-stream"
    maintype, subtype = content_type.split("/", 1)
    return path.read_bytes(), maintype, subtype


def build_mime_message(gmail_create_draft_args: dict[str, Any]) -> EmailMessage:
    to = str(gmail_create_draft_args.get("to") or "").strip()
    subject = str(gmail_create_draft_args.get("subject") or "").strip()
    body = str(gmail_create_draft_args.get("body") or "")
    attachment_values = gmail_create_draft_args.get("attachment_files")
    if not to:
        raise IntakeError("Gmail draft args are missing recipient.")
    if not subject:
        raise IntakeError("Gmail draft args are missing subject.")
    if not isinstance(attachment_values, list) or not attachment_values:
        raise IntakeError("Gmail draft args must include attachment_files as a non-empty array.")

    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    for value in attachment_values:
        raw_path = Path(str(value or "").strip())
        if not raw_path.is_absolute():
            raise IntakeError(f"Gmail attachment path is not an absolute existing file: {value}")
        path = raw_path.resolve()
        if not path.exists() or not path.is_file():
            raise IntakeError(f"Gmail attachment path is not an absolute existing file: {value}")
        data, maintype, subtype = _attachment_bytes(path)
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)
    return message


def base64url_message(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def gmail_draft_resource_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    errors = validate_draft_payload(payload)
    if errors:
        raise IntakeError("Draft payload is not Gmail-ready: " + "; ".join(errors))
    args = payload.get("gmail_create_draft_args")
    if not isinstance(args, dict):
        raise IntakeError("Draft payload is missing gmail_create_draft_args.")
    message = build_mime_message(args)
    return {"message": {"raw": base64url_message(message)}}


def create_gmail_draft_from_payload(payload: dict[str, Any], config_path: Path) -> dict[str, Any]:
    request_body = gmail_draft_resource_from_payload(payload)
    if fake_gmail_draft_api_enabled():
        digest = hashlib.sha256(str(request_body.get("message", {}).get("raw") or "").encode("utf-8")).hexdigest()[:16]
        args = payload.get("gmail_create_draft_args") if isinstance(payload.get("gmail_create_draft_args"), dict) else {}
        return {
            "status": "created",
            "provider": "gmail_api",
            "gmail_api_action": "users.drafts.create",
            "fake_mode": True,
            "draft_id": f"draft-smoke-{digest}",
            "message_id": f"message-smoke-{digest}",
            "thread_id": f"thread-smoke-{digest}",
            "to": str(args.get("to") or payload.get("to") or ""),
            "subject": str(args.get("subject") or payload.get("subject") or ""),
            "attachment_files": list(args.get("attachment_files") or payload.get("attachment_files") or []),
            "attachment_basenames": list(payload.get("attachment_basenames") or []),
            "attachment_sha256": dict(payload.get("attachment_sha256") or {}),
            "draft_only": True,
            "send_allowed": False,
        }
    access_token, _token = gmail_access_token(config_path)
    with httpx.Client(timeout=60) as client:
        try:
            response = client.post(
                GMAIL_DRAFTS_CREATE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json=request_body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _google_error_message(exc.response, "Google rejected the draft creation request.")
            raise IntakeError(f"Gmail Draft API create failed: {detail}. No local draft record or duplicate-index entry was written.") from exc
        except httpx.RequestError as exc:
            raise IntakeError("Gmail Draft API create failed because the network request did not complete. No local draft record or duplicate-index entry was written.") from exc
        data = response.json()
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    draft_id = str(data.get("id") or "").strip()
    message_id = str(message.get("id") or "").strip()
    thread_id = str(message.get("threadId") or message.get("thread_id") or "").strip()
    if not draft_id or not message_id:
        raise IntakeError("Gmail Draft API response did not include draft and message IDs.")
    args = payload.get("gmail_create_draft_args") if isinstance(payload.get("gmail_create_draft_args"), dict) else {}
    return {
        "status": "created",
        "provider": "gmail_api",
        "gmail_api_action": "users.drafts.create",
        "draft_id": draft_id,
        "message_id": message_id,
        "thread_id": thread_id,
        "to": str(args.get("to") or payload.get("to") or ""),
        "subject": str(args.get("subject") or payload.get("subject") or ""),
        "attachment_files": list(args.get("attachment_files") or payload.get("attachment_files") or []),
        "attachment_basenames": list(payload.get("attachment_basenames") or []),
        "attachment_sha256": dict(payload.get("attachment_sha256") or {}),
        "draft_only": True,
        "send_allowed": False,
    }


def _gmail_message_header(message: dict[str, Any], name: str) -> str:
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
    wanted = name.lower()
    for item in headers:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").lower() == wanted:
            return str(item.get("value") or "")
    return ""


def _safe_draft_id(value: str) -> str:
    draft_id = str(value or "").strip()
    if not draft_id:
        raise IntakeError("Gmail draft verification requires a draft ID.")
    if any(separator in draft_id for separator in ("/", "\\")):
        raise IntakeError("Gmail draft ID must not contain path separators.")
    return draft_id


def _verification_base(
    *,
    draft_id: str,
    expected_message_id: str = "",
    expected_thread_id: str = "",
) -> dict[str, Any]:
    return {
        "provider": "gmail_api",
        "gmail_api_action": "users.drafts.get",
        "draft_id": draft_id,
        "expected_message_id": str(expected_message_id or "").strip(),
        "expected_thread_id": str(expected_thread_id or "").strip(),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "draft_only": True,
        "send_allowed": False,
        "write_allowed": False,
        "managed_data_changed": False,
        "local_records_changed": False,
    }


def _not_found_verification(
    *,
    draft_id: str,
    expected_message_id: str = "",
    expected_thread_id: str = "",
    fake_mode: bool = False,
) -> dict[str, Any]:
    return {
        **_verification_base(
            draft_id=draft_id,
            expected_message_id=expected_message_id,
            expected_thread_id=expected_thread_id,
        ),
        "status": "not_found",
        "exists": False,
        "verified": True,
        "fake_mode": fake_mode,
        "message": "Gmail did not find this draft. Local records were not changed.",
    }


def _found_verification(
    *,
    draft_id: str,
    message_id: str,
    thread_id: str = "",
    expected_message_id: str = "",
    expected_thread_id: str = "",
    to: str = "",
    subject: str = "",
    fake_mode: bool = False,
) -> dict[str, Any]:
    expected_message = str(expected_message_id or "").strip()
    expected_thread = str(expected_thread_id or "").strip()
    found_message = str(message_id or "").strip()
    found_thread = str(thread_id or "").strip()
    message_matches = not expected_message or expected_message == found_message
    thread_matches = not expected_thread or expected_thread == found_thread
    reconciliation_mismatch = not message_matches or not thread_matches
    return {
        **_verification_base(
            draft_id=draft_id,
            expected_message_id=expected_message,
            expected_thread_id=expected_thread,
        ),
        "status": "reconciliation_mismatch" if reconciliation_mismatch else "verified",
        "exists": True,
        "verified": True,
        "fake_mode": fake_mode,
        "message_id": found_message,
        "thread_id": found_thread,
        "message_id_matches": message_matches,
        "thread_id_matches": thread_matches,
        "to": str(to or ""),
        "subject": str(subject or ""),
        "message": (
            "Gmail draft exists, but its Gmail IDs differ from the local record. "
            "This was a read-only check; local records were not changed."
            if reconciliation_mismatch
            else "Gmail draft exists. This was a read-only check; local records were not changed."
        ),
    }


def verify_gmail_draft_exists(payload: dict[str, Any], config_path: Path) -> dict[str, Any]:
    draft_id = _safe_draft_id(str(payload.get("draft_id") or payload.get("id") or ""))
    expected_message_id = str(payload.get("expected_message_id") or payload.get("message_id") or "").strip()
    expected_thread_id = str(payload.get("expected_thread_id") or payload.get("thread_id") or "").strip()

    if fake_gmail_draft_api_enabled():
        lowered = draft_id.lower()
        if "missing" in lowered or "not-found" in lowered or "not_found" in lowered:
            return _not_found_verification(
                draft_id=draft_id,
                expected_message_id=expected_message_id,
                expected_thread_id=expected_thread_id,
                fake_mode=True,
            )
        digest = hashlib.sha256(draft_id.encode("utf-8")).hexdigest()[:16]
        message_id = expected_message_id or f"message-smoke-{digest}"
        thread_id = expected_thread_id or f"thread-smoke-{digest}"
        return _found_verification(
            draft_id=draft_id,
            message_id=message_id,
            thread_id=thread_id,
            expected_message_id=expected_message_id,
            expected_thread_id=expected_thread_id,
            fake_mode=True,
        )

    access_token, _token = gmail_access_token(config_path)
    with httpx.Client(timeout=30) as client:
        try:
            response = client.get(
                gmail_draft_get_url(draft_id),
                headers={"Authorization": f"Bearer {access_token}"},
                params=[
                    ("format", "metadata"),
                    ("metadataHeaders", "To"),
                    ("metadataHeaders", "Subject"),
                ],
            )
        except httpx.RequestError as exc:
            raise IntakeError("Gmail draft verification failed because the network request did not complete. Local records were not changed.") from exc
        if response.status_code == 404:
            return _not_found_verification(
                draft_id=draft_id,
                expected_message_id=expected_message_id,
                expected_thread_id=expected_thread_id,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _google_error_message(exc.response, "Google rejected the draft verification request.")
            raise IntakeError(f"Gmail draft verification failed: {detail}. Local records were not changed.") from exc
        data = response.json()

    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    found_draft_id = str(data.get("id") or draft_id).strip()
    message_id = str(message.get("id") or "").strip()
    thread_id = str(message.get("threadId") or message.get("thread_id") or "").strip()
    if not found_draft_id:
        found_draft_id = draft_id
    return _found_verification(
        draft_id=found_draft_id,
        message_id=message_id,
        thread_id=thread_id,
        expected_message_id=expected_message_id,
        expected_thread_id=expected_thread_id,
        to=_gmail_message_header(message, "To"),
        subject=_gmail_message_header(message, "Subject"),
    )
