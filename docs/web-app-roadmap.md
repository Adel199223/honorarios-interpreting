# Honorários Super App Roadmap

The web app is a standalone local-first app for in-person interpreting honorários requests. LegalPDF Translate is used only as UI/product inspiration; this project keeps the authoritative PDF-only generator, duplicate index, service profiles, and Gmail draft safety rules.

## Implemented MVP

- FastAPI/Jinja browser app in `honorarios_app/`.
- LegalPDF-style app shell with New Job, Recent Work, More/References, dark workspace panels, cyan status chips, result cards, and a drawer-style Interpretation review surface.
- Profile-based intake creation using `data/service-profiles.json`.
- Review endpoint that classifies translation/word-count requests before asking questions.
- Local notification PDF upload with `pypdf` text recovery and candidate field extraction.
- Local photo/screenshot upload with safe stored previews and Pillow metadata extraction.
- Optional OpenAI OCR/autofill for photos and weak/scanned PDFs, with `/api/ai/status` and review-only AI evidence.
- Google Photos selected-photo bridge: choose/download one photo locally, paste visible Google Photos metadata, and recover it through the existing local photo pipeline.
- Secret-free `/api/google-photos/status` for future OAuth Picker readiness without exposing client secrets, tokens, raw picker URLs, media IDs, or photo URLs.
- Source evidence cards for recovered filename, metadata date, case number, recipient, crop/partial-image warnings, and missing questions.
- Synthetic rotated/cropped legal-photo fixture coverage for Google Photos metadata dates, leading-zero case normalization, and review-only AI warnings.
- Weak/scanned notification PDF page rendering for OpenAI recovery, including multi-page source evidence thumbnails and a safe `pdftoppm`-missing warning.
- Numbered missing-information questions.
- Duplicate and active-draft warnings before generation.
- Portuguese draft-text preview before PDF creation.
- PDF plus Gmail `_create_draft` payload preparation through the existing preflight path.
- PNG PDF preview URLs when `pdftoppm` is available; otherwise a non-send preview warning.
- Exact `gmail_create_draft_args` display in the review drawer.
- Draft lifecycle panel with active-check, correction mode, copyable draft handoff args, status recording, and replacement/superseded draft tracking.
- Draft recording endpoints that update the draft log and duplicate index without adding any Gmail send/trash action.
- Editable reference screens for known destinations/kilometers and court email directory entries, with validation and no send-capable behavior.
- Guarded service-profile editor with recipient validation, service/date/entity checks, and a sample Portuguese draft preview before saving.
- Profile diff preview and local profile-change history so service profile edits are auditable without publishing private runtime logs.
- Profile rollback from local profile-change history, with preview-first restore controls and stale-current-profile protection.
- Public GitHub Readiness privacy gate in the app and CLI (`scripts/public_release_gate.py`) to block publishing while private paths, generated artifacts, real court emails, personal payment details, or secret-like values remain.
- Sanitized public-candidate builder in the app and CLI (`scripts/build_public_candidate.py`) that copies only publishable source/doc files, replaces real local data with synthetic fixtures, and reruns the privacy gate against the candidate tree.

## LegalPDF UI Alignment

The standalone app intentionally mirrors the LegalPDF Translate Interpretation section at the layout and component-name level so future reintegration can be smoother without coupling the codebases today.

Shared-style UI concepts include:

- `app-shell`, `sidebar`, `nav-button`, `sidebar-more`, and `sidebar-card` for the left navigation.
- `panel`, `topbar`, `eyebrow`, `task-switcher`, `result-card`, and `status-chip` for the main workspace.
- `Start Interpretation Request`, `Review Case Details`, and `Review Interpretation Request` as the page flow.
- `workspace-drawer` and `workspace-drawer-interpretation` as the review surface for draft text, PDF generation, Gmail draft payloads, and draft recording.

Project-specific behavior must remain here until a later integration adapter exists:

- PDF generation uses this project's ReportLab pipeline, not LegalPDF's DOCX/Word-COM path.
- Duplicate protection, service profiles, PJ/GNR host-building rules, numbered questions, and translation set-aside rules come from this project.
- Gmail handling stays draft-only through prepared `_create_draft` payloads; no send action should be added to the UI.

## Next Stages

1. Add full Google Photos OAuth Picker import, using the LegalPDF reference pattern, only after local credential/token storage is reviewed and sanitized diagnostics are in place.
2. Review the generated sanitized public candidate, add final repo metadata such as license/release notes, then initialize and publish from that candidate only.

## Public GitHub Readiness

Public GitHub is deliberately blocked for the current working folder. It contains private local configuration, real generated PDFs, draft logs, duplicate records, and workflow history. Use `scripts/build_public_candidate.py` or the app's Build sanitized candidate button to create `output/public-candidate`, then publish only after reviewing that candidate and confirming its privacy gate passes.

## Non-Negotiable Safety Rules

- Never call Gmail send actions from the app.
- Never treat a closing/signature date as the service date.
- Never generate for translation/word-count sources.
- Never ignore `drafted` duplicate records.
- Never publish real PDFs, Gmail IDs, personal profile/payment data, or real case history.
