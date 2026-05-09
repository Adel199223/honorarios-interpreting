from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from scripts.generate_pdf import IntakeError
from scripts.build_public_candidate import build_public_candidate
from scripts.public_release_gate import analyze_public_readiness

from .services import (
    AppPaths,
    ai_status_payload,
    apply_legalpdf_restore,
    apply_legalpdf_adapter_import_plan,
    apply_numbered_answers,
    backup_status_payload,
    build_legalpdf_adapter_import_plan,
    build_profile_intake,
    build_legalpdf_integration_checklist,
    diagnostics_status_payload,
    draft_lifecycle_for_intake,
    export_legalpdf_import_report,
    export_local_backup,
    google_photos_status_payload,
    google_photos_create_picker_session,
    google_photos_import_selected,
    google_photos_list_session_media,
    google_photos_oauth_callback,
    google_photos_oauth_start,
    gmail_api_config_save,
    gmail_api_draft_verify,
    gmail_api_oauth_callback,
    gmail_api_oauth_start,
    gmail_api_status,
    manual_handoff_packet,
    legalpdf_adapter_contract,
    legalpdf_apply_report_detail,
    legalpdf_apply_history,
    legalpdf_apply_restore_plan,
    load_app_reference,
    new_personal_profile,
    personal_profiles_summary,
    preflight_intakes,
    prepare_intakes,
    require_current_preflight_review,
    apply_legalpdf_personal_profile_import,
    record_draft,
    recover_source_upload,
    review_intake,
    review_intake_with_profile_evidence,
    resolve_artifact_path,
    create_and_record_gmail_api_draft,
    preview_local_backup_import,
    preview_court_email_upsert,
    preview_known_destination_upsert,
    preview_legalpdf_personal_profile_import,
    preview_legalpdf_import,
    preview_service_profile_upsert,
    preview_profile_rollback,
    rollback_service_profile,
    delete_personal_profile,
    save_personal_profile,
    set_main_personal_profile,
    restore_local_backup,
    store_supporting_attachment_upload,
    upsert_court_email,
    upsert_known_destination,
    upsert_service_profile,
)
from .runtime import create_synthetic_runtime, runtime_path_overrides


PACKAGE_DIR = Path(__file__).resolve().parent


def build_paths(**overrides: Any) -> AppPaths:
    values = {key: Path(value) for key, value in overrides.items() if value is not None}
    return AppPaths(**values)


def static_asset_version() -> str:
    static_dir = PACKAGE_DIR / "static"
    asset_paths = [static_dir / "app.js", static_dir / "style.css"]
    mtimes = [path.stat().st_mtime_ns for path in asset_paths if path.exists()]
    return str(max(mtimes)) if mtimes else "dev"


def create_app(**path_overrides: Any) -> FastAPI:
    paths = build_paths(**path_overrides)
    app = FastAPI(
        title="Honorários Interpreting",
        version="0.1.0",
        description="Local-first app for interpretation honorários PDFs and Gmail draft payloads.",
    )
    app.state.paths = paths

    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", {"asset_version": static_asset_version()})

    @app.get("/api/reference")
    async def api_reference() -> dict[str, Any]:
        try:
            return load_app_reference(paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/reference/destinations")
    async def api_reference_destination(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return upsert_known_destination(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reference/destinations/preview")
    async def api_reference_destination_preview(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return preview_known_destination_upsert(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reference/court-emails")
    async def api_reference_court_email(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return upsert_court_email(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reference/court-emails/preview")
    async def api_reference_court_email_preview(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return preview_court_email_upsert(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reference/service-profiles")
    async def api_reference_service_profile(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return upsert_service_profile(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reference/service-profiles/preview")
    async def api_reference_service_profile_preview(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return preview_service_profile_upsert(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reference/service-profiles/rollback-preview")
    async def api_reference_service_profile_rollback_preview(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return preview_profile_rollback(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reference/service-profiles/rollback")
    async def api_reference_service_profile_rollback(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return rollback_service_profile(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/ai/status")
    async def api_ai_status() -> dict[str, Any]:
        return ai_status_payload(paths.ai_config)

    @app.get("/api/profiles/summary")
    async def api_profiles_summary() -> dict[str, Any]:
        try:
            return personal_profiles_summary(paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/profiles/new")
    async def api_profiles_new() -> dict[str, Any]:
        try:
            return new_personal_profile(paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/profiles/save")
    async def api_profiles_save(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return save_personal_profile(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/profiles/set-main")
    async def api_profiles_set_main(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return set_main_personal_profile(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/profiles/delete")
    async def api_profiles_delete(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return delete_personal_profile(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/profiles/import-legalpdf-preview")
    async def api_profiles_import_legalpdf_preview(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return preview_legalpdf_personal_profile_import(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/profiles/import-legalpdf")
    async def api_profiles_import_legalpdf(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return apply_legalpdf_personal_profile_import(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/diagnostics/status")
    async def api_diagnostics_status() -> dict[str, Any]:
        return diagnostics_status_payload()

    @app.get("/api/google-photos/status")
    async def api_google_photos_status() -> dict[str, Any]:
        return google_photos_status_payload(paths.google_photos_config)

    @app.post("/api/google-photos/oauth/start")
    async def api_google_photos_oauth_start() -> dict[str, Any]:
        try:
            return google_photos_oauth_start(paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/google-photos/oauth/callback")
    async def api_google_photos_oauth_callback(code: str = "", state: str = "") -> dict[str, Any]:
        try:
            return google_photos_oauth_callback(code=code, state=state, paths=paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/google-photos/picker/session")
    async def api_google_photos_picker_session(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return google_photos_create_picker_session(payload or {}, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/google-photos/picker/session/{session_id}")
    async def api_google_photos_picker_session_media(session_id: str) -> dict[str, Any]:
        try:
            return google_photos_list_session_media(session_id, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/google-photos/picker/import")
    async def api_google_photos_picker_import(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return google_photos_import_selected(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/gmail/status")
    async def api_gmail_status() -> dict[str, Any]:
        return gmail_api_status(paths)

    @app.post("/api/gmail/config")
    async def api_gmail_config_save(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return gmail_api_config_save(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/gmail/oauth/start")
    async def api_gmail_oauth_start() -> dict[str, Any]:
        try:
            return gmail_api_oauth_start(paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/gmail/oauth/callback")
    async def api_gmail_oauth_callback(code: str = "", state: str = "") -> dict[str, Any]:
        try:
            return gmail_api_oauth_callback(code=code, state=state, paths=paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/gmail/drafts/create")
    async def api_gmail_drafts_create(payload: dict[str, Any]) -> Any:
        try:
            return create_and_record_gmail_api_draft(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "draft_only": True,
                "send_allowed": False,
            })

    @app.post("/api/gmail/drafts/verify")
    async def api_gmail_drafts_verify(payload: dict[str, Any]) -> Any:
        try:
            return gmail_api_draft_verify(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "gmail_api_action": "users.drafts.get",
                "read_only": True,
                "draft_only": True,
                "send_allowed": False,
                "write_allowed": False,
                "managed_data_changed": False,
                "local_records_changed": False,
            })

    @app.post("/api/gmail/manual-handoff")
    async def api_gmail_manual_handoff(payload: dict[str, Any]) -> Any:
        try:
            return manual_handoff_packet(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "mode": "manual_handoff",
                "draft_only": True,
                "send_allowed": False,
                "write_allowed": False,
                "managed_data_changed": False,
            })

    @app.get("/api/public-readiness")
    async def api_public_readiness() -> dict[str, Any]:
        return analyze_public_readiness(paths.profile.parents[1])

    @app.post("/api/public-candidate/build")
    async def api_public_candidate_build() -> dict[str, Any]:
        try:
            return build_public_candidate(paths.profile.parents[1])
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/backup/export")
    async def api_backup_export() -> dict[str, Any]:
        try:
            return export_local_backup(paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/backup/status")
    async def api_backup_status() -> dict[str, Any]:
        try:
            return backup_status_payload(paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/backup/import-preview")
    async def api_backup_import_preview(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return preview_local_backup_import(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/backup/import")
    async def api_backup_import(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return restore_local_backup(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/integration/import-preview")
    async def api_integration_import_preview(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return preview_legalpdf_import(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/integration/adapter-contract")
    async def api_integration_adapter_contract() -> dict[str, Any]:
        return legalpdf_adapter_contract(paths)

    @app.post("/api/integration/import-report")
    async def api_integration_import_report(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return export_legalpdf_import_report(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/integration/checklist")
    async def api_integration_checklist(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return build_legalpdf_integration_checklist(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/integration/import-plan")
    async def api_integration_import_plan(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return build_legalpdf_adapter_import_plan(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/integration/apply-import-plan")
    async def api_integration_apply_import_plan(payload: dict[str, Any]) -> Any:
        try:
            result = apply_legalpdf_adapter_import_plan(payload, paths)
            if result.get("status") == "blocked":
                return JSONResponse(status_code=400, content=result)
            return result
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "write_allowed": False,
                "managed_data_changed": False,
                "legalpdf_write_allowed": False,
                "send_allowed": False,
            })

    @app.get("/api/integration/apply-history")
    async def api_integration_apply_history(limit: int = 20) -> dict[str, Any]:
        try:
            return legalpdf_apply_history(paths, limit=limit)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/integration/apply-detail")
    async def api_integration_apply_detail(report_id: str) -> Any:
        try:
            return legalpdf_apply_report_detail(paths, report_id=report_id)
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "write_allowed": False,
                "managed_data_changed": False,
                "legalpdf_write_allowed": False,
                "send_allowed": False,
            })

    @app.get("/api/integration/apply-restore-plan")
    async def api_integration_apply_restore_plan(report_id: str) -> Any:
        try:
            return legalpdf_apply_restore_plan(paths, report_id=report_id)
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "restore_allowed": False,
                "write_allowed": False,
                "managed_data_changed": False,
                "legalpdf_write_allowed": False,
                "send_allowed": False,
            })

    @app.post("/api/integration/apply-restore")
    async def api_integration_apply_restore(payload: dict[str, Any]) -> Any:
        try:
            result = apply_legalpdf_restore(payload, paths)
            if result.get("status") == "blocked":
                return JSONResponse(status_code=400, content=result)
            return result
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "restore_allowed": False,
                "write_allowed": False,
                "managed_data_changed": False,
                "legalpdf_write_allowed": False,
                "send_allowed": False,
            })

    @app.post("/api/intake/from-profile")
    async def api_intake_from_profile(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            intake = build_profile_intake(payload, paths)
            return {"status": "created", "intake": intake, "review": review_intake_with_profile_evidence(intake, paths)}
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/review")
    async def api_review(payload: dict[str, Any]) -> dict[str, Any]:
        intake = payload.get("intake", payload)
        if not isinstance(intake, dict):
            raise HTTPException(status_code=400, detail="Request must include an intake object.")
        return review_intake_with_profile_evidence(intake, paths)

    @app.post("/api/review/apply-answers")
    async def api_review_apply_answers(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return apply_numbered_answers(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/drafts/active-check")
    async def api_drafts_active_check(payload: dict[str, Any]) -> dict[str, Any]:
        intake = payload.get("intake", payload)
        if not isinstance(intake, dict):
            raise HTTPException(status_code=400, detail="Request must include an intake object.")
        try:
            return draft_lifecycle_for_intake(intake, paths)
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "send_allowed": False,
            })

    @app.post("/api/sources/upload")
    async def api_source_upload(
        file: UploadFile = File(...),
        source_kind: str = Form(...),
        profile: str = Form(""),
        personal_profile_id: str = Form(""),
        visible_text: str = Form(""),
        visible_metadata_text: str = Form(""),
        ai_recovery: str = Form("auto"),
    ) -> dict[str, Any]:
        try:
            content = await file.read()
            return recover_source_upload(
                filename=file.filename or "source",
                content_type=file.content_type or "",
                content=content,
                source_kind=source_kind,
                profile_name=profile,
                personal_profile_id=personal_profile_id,
                visible_text=visible_text or visible_metadata_text,
                ai_recovery_mode=ai_recovery,
                paths=paths,
            )
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/attachments/upload")
    async def api_attachment_upload(
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        try:
            content = await file.read()
            return store_supporting_attachment_upload(
                filename=file.filename or "supporting-attachment",
                content_type=file.content_type or "",
                content=content,
                paths=paths,
            )
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/artifacts/{root_key}/{relative_path:path}")
    async def api_artifact(root_key: str, relative_path: str) -> FileResponse:
        try:
            path = resolve_artifact_path(root_key, relative_path, paths)
            return FileResponse(path)
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/prepare")
    async def api_prepare(payload: dict[str, Any]) -> dict[str, Any]:
        intakes = payload.get("intakes")
        if intakes is None and isinstance(payload.get("intake"), dict):
            intakes = [payload["intake"]]
        if not isinstance(intakes, list) or not all(isinstance(item, dict) for item in intakes):
            raise HTTPException(status_code=400, detail="Request must include intakes as a list of objects.")
        if "allow_duplicate" in payload:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": "allow_duplicate is not accepted by the browser app. Use correction mode only for intentional draft replacements.",
                "send_allowed": False,
            })
        if "allow_existing_draft" in payload:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": "allow_existing_draft is not accepted by the browser app. Use correction_mode=true with a short correction_reason.",
                "send_allowed": False,
            })
        correction_mode = bool(payload.get("correction_mode", False))
        correction_reason = str(payload.get("correction_reason") or "").strip()
        if correction_mode and not correction_reason:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": "Correction mode requires a reason before preparing a replacement draft.",
                "send_allowed": False,
            })
        try:
            packet_mode = bool(payload.get("packet_mode", False))
            if packet_mode or len(intakes) > 1:
                require_current_preflight_review(
                    payload,
                    intakes,
                    paths,
                    packet_mode=packet_mode,
                    correction_reason=correction_reason if correction_mode else "",
                )
            return prepare_intakes(
                intakes,
                paths,
                render_previews=bool(payload.get("render_previews", False)),
                allow_duplicate=False,
                allow_existing_draft=False,
                correction_reason=correction_reason if correction_mode else "",
                packet_mode=packet_mode,
            )
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "send_allowed": False,
            })

    @app.post("/api/prepare/preflight")
    async def api_prepare_preflight(payload: dict[str, Any]) -> dict[str, Any]:
        intakes = payload.get("intakes")
        if intakes is None and isinstance(payload.get("intake"), dict):
            intakes = [payload["intake"]]
        if not isinstance(intakes, list) or not all(isinstance(item, dict) for item in intakes):
            raise HTTPException(status_code=400, detail="Request must include intakes as a list of objects.")
        if "allow_duplicate" in payload:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": "allow_duplicate is not accepted by the browser app. Use correction mode only for intentional draft replacements.",
                "send_allowed": False,
                "write_allowed": False,
            })
        if "allow_existing_draft" in payload:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": "allow_existing_draft is not accepted by the browser app. Use correction_mode=true with a short correction_reason.",
                "send_allowed": False,
                "write_allowed": False,
            })
        correction_mode = bool(payload.get("correction_mode", False))
        correction_reason = str(payload.get("correction_reason") or "").strip()
        try:
            return preflight_intakes(
                intakes,
                paths,
                allow_duplicate=False,
                allow_existing_draft=False,
                correction_reason=correction_reason if correction_mode else "",
                packet_mode=bool(payload.get("packet_mode", False)),
            )
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "send_allowed": False,
                "write_allowed": False,
            })

    @app.post("/api/drafts/record")
    async def api_record_draft(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return record_draft(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "send_allowed": False,
            })

    @app.post("/api/drafts/status")
    async def api_draft_status(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return record_draft(payload, paths)
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "send_allowed": False,
            })

    @app.get("/api/history")
    async def api_history() -> dict[str, Any]:
        reference = load_app_reference(paths)
        return {
            "duplicates": reference["duplicates"],
            "draft_log": reference["draft_log"],
            "send_allowed": False,
        }

    return app


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local Honorários browser app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--runtime-root", type=Path, help="Use config/data/output paths under this disposable runtime root.")
    parser.add_argument("--init-synthetic-runtime", action="store_true", help="Create synthetic local runtime files under --runtime-root before starting.")
    parser.add_argument("--seed-active-draft", action="store_true", help="With --init-synthetic-runtime, seed one synthetic active draft for replacement smoke.")
    args = parser.parse_args(argv)

    if args.runtime_root:
        if args.init_synthetic_runtime:
            create_synthetic_runtime(args.runtime_root, seed_active_draft=args.seed_active_draft)
        runtime_app = create_app(**runtime_path_overrides(args.runtime_root))
        uvicorn.run(runtime_app, host=args.host, port=args.port, reload=False)
    else:
        uvicorn.run("honorarios_app.web:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
