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
    apply_numbered_answers,
    backup_status_payload,
    build_legalpdf_adapter_import_plan,
    build_profile_intake,
    build_legalpdf_integration_checklist,
    draft_lifecycle_for_intake,
    export_legalpdf_import_report,
    export_local_backup,
    google_photos_status_payload,
    google_photos_create_picker_session,
    google_photos_import_selected,
    google_photos_list_session_media,
    google_photos_oauth_callback,
    google_photos_oauth_start,
    load_app_reference,
    prepare_intakes,
    record_draft,
    recover_source_upload,
    review_intake,
    resolve_artifact_path,
    preview_local_backup_import,
    preview_legalpdf_import,
    preview_service_profile_upsert,
    preview_profile_rollback,
    rollback_service_profile,
    restore_local_backup,
    upsert_court_email,
    upsert_known_destination,
    upsert_service_profile,
)


PACKAGE_DIR = Path(__file__).resolve().parent


def build_paths(**overrides: Any) -> AppPaths:
    values = {key: Path(value) for key, value in overrides.items() if value is not None}
    return AppPaths(**values)


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
        return templates.TemplateResponse(request, "index.html", {})

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

    @app.post("/api/reference/court-emails")
    async def api_reference_court_email(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return upsert_court_email(payload, paths)
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

    @app.post("/api/intake/from-profile")
    async def api_intake_from_profile(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            intake = build_profile_intake(payload, paths)
            return {"status": "created", "intake": intake, "review": review_intake(intake, paths)}
        except (IntakeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/review")
    async def api_review(payload: dict[str, Any]) -> dict[str, Any]:
        intake = payload.get("intake", payload)
        if not isinstance(intake, dict):
            raise HTTPException(status_code=400, detail="Request must include an intake object.")
        return review_intake(intake, paths)

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
                visible_text=visible_text or visible_metadata_text,
                ai_recovery_mode=ai_recovery,
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
        correction_mode = bool(payload.get("correction_mode", False))
        correction_reason = str(payload.get("correction_reason") or "").strip()
        if bool(payload.get("allow_existing_draft", False)) and not correction_reason:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": "Correction mode requires a reason before preparing over an existing Gmail draft.",
                "send_allowed": False,
            })
        if correction_mode and not correction_reason:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": "Correction mode requires a reason before preparing a replacement draft.",
                "send_allowed": False,
            })
        try:
            return prepare_intakes(
                intakes,
                paths,
                render_previews=bool(payload.get("render_previews", False)),
                allow_duplicate=bool(payload.get("allow_duplicate", False)),
                allow_existing_draft=bool(payload.get("allow_existing_draft", False)),
                correction_reason=correction_reason if correction_mode or payload.get("allow_existing_draft") else "",
                packet_mode=bool(payload.get("packet_mode", False)),
            )
        except (IntakeError, OSError, ValueError) as exc:
            return JSONResponse(status_code=400, content={
                "status": "blocked",
                "message": str(exc),
                "send_allowed": False,
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
    args = parser.parse_args(argv)

    uvicorn.run("honorarios_app.web:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
