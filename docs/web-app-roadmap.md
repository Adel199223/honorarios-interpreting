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
- Automatic service-profile selection for uploads: deterministic local rules score recovered source text and AI evidence, auto-apply only high-confidence profile matches, and keep explicit user-selected profiles as overrides.
- Guarded profile proposals for new recurring patterns: when auto-detect falls back to generic but the upload evidence contains a service place, payment entity, recipient, and kilometers, Source Evidence can prepare a reusable profile payload for review in the guarded profile editor.
- Google Photos selected-photo bridge: choose/download one photo locally, paste visible Google Photos metadata, and recover it through the existing local photo pipeline.
- Google Photos OAuth Picker import with secret-free status, OAuth start/callback, Picker session creation, selected-media import, and no exposure of client secrets, tokens, media IDs, base URLs, or photo URLs in app output.
- Source evidence cards for recovered filename, profile decision, metadata date, case number, recipient, crop/partial-image warnings, and missing questions.
- Synthetic rotated/cropped legal-photo fixture coverage for Google Photos metadata dates, leading-zero case normalization, and review-only AI warnings.
- Weak/scanned notification PDF page rendering for OpenAI recovery, including multi-page source evidence thumbnails and a safe `pdftoppm`-missing warning.
- Numbered missing-information questions.
- Review-drawer `Numbered answers` application, so compact replies like `1. Beja` update the active intake and rerun review without manual JSON edits.
- Duplicate and active-draft warnings before generation.
- Portuguese draft-text preview before PDF creation.
- PDF plus Gmail `_create_draft` payload preparation through the existing preflight path.
- PNG PDF preview URLs when `pdftoppm` is available; otherwise a non-send preview warning.
- Exact `gmail_create_draft_args` display in the review drawer.
- Draft lifecycle panel with active-check, correction mode, copyable draft handoff args, status recording, and replacement/superseded draft tracking.
- Draft recording endpoints that update the draft log and duplicate index without adding any Gmail send/trash action.
- Recent Work lifecycle filters for `active`, `drafted`, `sent`, `superseded`, `trashed`, and `not_found` records, so blocking drafts and historical corrections can be separated quickly.
- Browser Batch Queue for repeated same-profile or same-case services, using the existing all-or-nothing multi-intake `/api/prepare` contract.
- Packet mode in the Batch Queue for same-recipient batches that should produce one combined PDF attachment and one Gmail draft payload while still tracking every underlying case/date/period.
- Packet-order controls in the Batch Queue, with drag/drop plus `Move up` / `Move down`, so the combined PDF order is explicit before packet generation.
- Packet item inspector in the Batch Queue, so each queued request can be checked beside its generated requerimento PDF slot and any supporting attachments before packet generation.
- Prepared-packet draft recording helper that copies a `record_gmail_draft.py` command template and JSON object for logging the packet draft plus its underlying duplicate blockers.
- Record Gmail Draft autofill from the latest prepared packet or individual payload, preserving pasted Gmail draft/message/thread IDs so the local draft log can be updated with fewer manual path mistakes.
- Gmail connector response parser in Record Gmail Draft, so pasted `_create_draft` JSON/text can fill draft/message/thread IDs before the prepared-payload autofill.
- One-click local `Record parsed response + prepared payload` action that parses a pasted `_create_draft` response, autofills the latest packet or individual payload, and records the draft locally without adding any Gmail send-capable behavior.
- Editable reference screens for known destinations/kilometers and court email directory entries, with validation and no send-capable behavior.
- Guarded service-profile editor with recipient validation, service/date/entity checks, and a sample Portuguese draft preview before saving.
- Profile diff preview and local profile-change history so service profile edits are auditable without publishing private runtime logs.
- Profile rollback from local profile-change history, with preview-first restore controls and stale-current-profile protection.
- Local Backup panel and API for exporting/restoring service profiles, court emails, known destinations, duplicate records, Gmail draft lifecycle logs, and profile-change history, with preview-first import, automatic pre-restore backup, `/api/backup/status`, and latest-backup reminders before high-risk local edits.
- LegalPDF Integration Preview panel plus `/api/integration/import-preview`, `/api/integration/import-report`, `/api/integration/checklist`, and `/api/integration/import-plan`, which compare backup contents, optional profile mappings, and court-email differences with `write_allowed: false`, optionally export a private Markdown/JSON preview report under `output/integration-reports/`, produce a read-only checklist of future adapter tasks, and build a read-only adapter import plan that blocks destructive profile or recipient changes before any future write-capable adapter exists.
- Public GitHub Readiness privacy gate in the app and CLI (`scripts/public_release_gate.py`) to block publishing while private paths, generated artifacts, real court emails, personal payment details, or secret-like values remain.
- Sanitized public-candidate builder in the app and CLI (`scripts/build_public_candidate.py`) that copies only publishable source/doc files, replaces real local data with synthetic fixtures, and reruns the privacy gate against the candidate tree.
- Generated public-candidate smoke tests for LegalPDF-style workflow landmarks, draft-only reference status, secret-free Google Photos status, read-only LegalPDF preview/report/checklist/import-plan APIs, and the privacy gate.
- Optional local live-app smoke runner (`scripts/local_app_smoke.py`) for checking the running private app's LegalPDF-style landmarks, draft-only endpoints, secret-free Google Photos status, and public-readiness endpoint without creating PDFs or Gmail drafts by default.
- Opt-in interaction smoke mode (`--interaction-checks`) that exercises profile intake, active-draft checking, packet-mode prepare, attachment-array validation, and underlying-request duplicate-tracking contract through injected test hooks or disposable local state while still requiring `send_allowed: false` throughout.
- Opt-in browser click-through smoke (`--browser-click-through`) that opens the app in a real browser driver when available, verifies the profile-to-review-drawer path, and adds a reviewed request to the batch queue without clicking prepare or recording drafts by default.
- Optional browser upload/correction smoke flags (`--browser-upload-photo`, `--browser-upload-pdf`, and `--browser-correction-mode`) that verify local Source Evidence and draft-lifecycle UI with disposable synthetic files while still blocking prepare, record, and draft-status endpoints by default.

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

## Public Repository

The sanitized public repository is live at:

<https://github.com/Adel199223/honorarios-interpreting>

It was published from `output/public-candidate` after the privacy and repository metadata gate passed, not from the private working folder.

## Next Stages

1. Add a write-confirmed adapter import prototype only after the read-only import plan proves its blockers and merge-policy labels are conservative enough.
2. Add a future explicit artifact-writing browser smoke for replacement-draft preparation only if it can run against disposable/synthetic state and preserve the no-Gmail-send rule.
3. For future public updates, rebuild the sanitized candidate, rerun the gate, and push from that candidate repository only.

## Public GitHub Readiness

Public GitHub is deliberately blocked for the current working folder. It contains private local configuration, real generated PDFs, draft logs, duplicate records, and workflow history. Use `scripts/build_public_candidate.py` or the app's Build sanitized candidate button to create `output/public-candidate`, then publish updates only after reviewing that candidate and confirming its privacy gate passes.

## Non-Negotiable Safety Rules

- Never call Gmail send actions from the app.
- Never treat a closing/signature date as the service date.
- Never generate for translation/word-count sources.
- Never ignore `drafted` duplicate records.
- Never publish real PDFs, Gmail IDs, personal profile/payment data, or real case history.
