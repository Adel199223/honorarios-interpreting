# Honorários Super App Roadmap

The web app is a standalone local-first app for in-person interpreting honorários requests. LegalPDF Translate is used only as UI/product inspiration; this project keeps the authoritative PDF-only generator, duplicate index, service profiles, and Gmail draft safety rules.

## Implemented MVP

- FastAPI/Jinja browser app in `honorarios_app/`.
- LegalPDF-style app shell with New Job, Recent Work, More/References, dark workspace panels, cyan status chips, result cards, and a drawer-style Interpretation review surface.
- LegalPDF-style personal Profiles route with main profile summary, profile records, drawer editor, local-only LegalPDF profile import preview/apply, and interpretation distance editing.
- Personal profile adapter that derives the existing generator `config/profile.json` contract from the selected main personal profile, while keeping private profile data in ignored `config/profiles.local.json`.
- Profile-based intake creation using `data/service-profiles.json`.
- Review endpoint that classifies translation/word-count requests before asking questions.
- Local notification PDF upload with `pypdf` text recovery and candidate field extraction.
- Local photo/screenshot upload with safe stored previews and Pillow metadata extraction.
- Drag-and-drop plus clipboard-paste local source intake for notification PDFs, photos, and screenshots, reusing the same safe upload endpoint, Source Evidence, and review-before-generation path.
- Browser supporting-proof/declaration intake: optional PDF/image attachments can be added to the active request, automatically stored as local source artifacts, inserted into `additional_attachment_files`, and paired with an email body that mentions documento(s) comprovativo(s), without creating PDFs, recording drafts, or touching Gmail.
- Optional OpenAI OCR/autofill for photos and weak/scanned PDFs, with `/api/ai/status`, a strict Responses JSON Schema named `honorarios_source_recovery`, domain prompt examples for PJ/GNR host buildings, Beringel/Beja, labor-court, medical-legal, and translation word-count cases, and review-only AI evidence.
- Automatic service-profile selection for uploads: deterministic local rules score recovered source text and AI evidence, auto-apply only high-confidence profile matches, and keep explicit user-selected profiles as overrides.
- Manual/pasted review also runs the service-profile evidence path: high-confidence known patterns can auto-fill profile defaults before questions/PDF generation, and unknown stable patterns can surface guarded profile proposals without saving reference data.
- Guarded profile proposals for new recurring patterns: when auto-detect falls back to generic but the upload evidence contains a service place, payment entity, recipient, and kilometers, Source Evidence can prepare a reusable profile payload for review in the guarded profile editor.
- Google Photos selected-photo bridge: choose/download one photo locally, paste visible Google Photos metadata, and recover it through the existing local photo pipeline.
- Google Photos OAuth Picker import with secret-free status, OAuth start/callback, Picker session creation, selected-media import, and no exposure of client secrets, tokens, media IDs, base URLs, or photo URLs in app output.
- Source evidence cards for recovered filename, profile decision, metadata date, case number, recipient, crop/partial-image warnings, and missing questions.
- Field-level evidence ledger for upload recovery, showing whether each recovered/applied value came from deterministic text, OpenAI OCR, image metadata, known destinations, or profile defaults, with review-only confidence/status chips plus AI schema/prompt version and missing-field evidence.
- `Review Attention` source summary that highlights blocked or review-needed upload states such as translation set-asides, missing numbered questions, metadata/date conflicts, duplicates, active drafts, AI recovery issues, source warnings, profile fallback, and profile proposals before any PDF or Gmail draft step.
- Synthetic rotated/cropped legal-photo fixture coverage for Google Photos metadata dates, leading-zero case normalization, and review-only AI warnings.
- Weak/scanned notification PDF page rendering for OpenAI recovery, including multi-page source evidence thumbnails and a safe `pdftoppm`-missing warning.
- Numbered missing-information questions.
- Review-drawer `Numbered answers` application, so compact replies like `1. Beja` update the active intake and rerun review without manual JSON edits.
- Duplicate and active-draft warnings before generation.
- CLI and browser correction preflight parity: preparing a replacement over an active draft requires an explicit correction reason, and the manifest keeps that reason for audit.
- `Suggested Next Step` guidance in the review surface, backed by the same review/preflight API response, for missing questions, translation set-aside, duplicates, active drafts, ready-to-prepare requests, and prepared Gmail draft args.
- Portuguese draft-text preview before PDF creation.
- PDF plus Gmail `_create_draft` payload preparation through the existing preflight path.
- PNG PDF preview URLs when `pdftoppm` is available; otherwise a non-send preview warning.
- Exact `gmail_create_draft_args` display in the review drawer.
- Gmail-safe handoff mode: `/api/gmail/status` reports Manual Draft Handoff as ready in every Gmail state, uses `recommended_mode: manual_handoff` when OAuth is disconnected, and uses `recommended_mode: gmail_api` only when OAuth is connected and direct draft creation is available. The review drawer still builds a copy-ready `_create_draft` handoff packet from the prepared payload before local record helpers are used.
- Optional local Gmail Draft API connector with ignored `config/gmail.local.json` and `config/gmail-token.local.json`, secret-free `/api/gmail/status`, guarded `/api/gmail/config` for saving pasted local OAuth desktop-client details, OAuth start/callback endpoints, and a guarded `Create Gmail Draft` action that calls only Gmail `users.drafts.create` after the PDF preview, exact draft args, and Gmail handoff checklist are current.
- Automatic draft recording after manual handoff or optional in-app Gmail draft creation, reusing the existing draft log and duplicate-index rules so each created draft becomes `status: drafted` immediately.
- Draft lifecycle panel with active-check, correction mode, copyable draft handoff args, status recording, and replacement/superseded draft tracking.
- Stale prepared-artifact invalidation: changing the source, review state, or intake form clears prepared PDF previews, draft payload paths, Gmail record-helper IDs, and active draft lifecycle state, forcing a fresh review/preflight before reuse.
- Draft recording endpoints that update the draft log and duplicate index without adding any Gmail send/trash action.
- Recent Work lifecycle filters for `active`, `drafted`, `sent`, `superseded`, `trashed`, and `not_found` records, plus row-level draft verification and local `Mark manually sent` bookkeeping after the user sends a draft in Gmail.
- Global `Reset workspace` action for clearing the current browser review, prepared payload state, correction fields, and Batch Queue without touching real local records or Gmail.
- Browser Batch Queue for repeated same-profile or same-case services, using the existing all-or-nothing multi-intake `/api/prepare` contract.
- Non-writing browser batch preflight through `/api/prepare/preflight`, so queued requests can be checked for missing information, duplicates, active drafts, attachment-body rules, and packet recipient mismatches before any PDF, draft payload, intake JSON, or manifest is written.
- Stale-aware batch gating: `Prepare batch package` is enabled only when the latest ready preflight matches the current queue order and packet-mode setting, so queue edits require a fresh non-writing check before artifact creation.
- Packet mode in the Batch Queue for same-recipient batches that should produce one combined PDF attachment and one Gmail draft payload while still tracking every underlying case/date/period.
- Packet-order controls in the Batch Queue, with drag/drop plus `Move up` / `Move down`, so the combined PDF order is explicit before packet generation.
- Packet item inspector in the Batch Queue, so each queued request can be checked beside its generated requerimento PDF slot and any supporting attachments before packet generation.
- Prepared-packet draft recording helper that copies a `record_gmail_draft.py` command template and JSON object for logging the packet draft plus its underlying duplicate blockers.
- Record Gmail Draft autofill from the latest prepared packet or individual payload, preserving pasted Gmail draft/message/thread IDs so the local draft log can be updated with fewer manual path mistakes.
- Gmail connector response parser in Record Gmail Draft, so pasted `_create_draft` JSON/text can fill draft/message/thread IDs before the prepared-payload autofill.
- One-click local `Record parsed response + prepared payload` action that parses a pasted `_create_draft` response, autofills the latest packet or individual payload, and records the draft locally without adding any Gmail send-capable behavior.
- Gmail handoff checklist gate for the one-click record helper, requiring explicit review of the PDF preview and exact `_create_draft` args before local draft-log writes.
- Editable reference screens for known destinations/kilometers and court email directory entries, with validation and no send-capable behavior.
- Guarded service-profile editor with recipient validation, service/date/entity checks, and a sample Portuguese draft preview before saving.
- Profile diff preview and local profile-change history so service profile edits are auditable without publishing private runtime logs.
- Profile rollback from local profile-change history, with preview-first restore controls and stale-current-profile protection.
- Local Backup panel and API for exporting/restoring service profiles, court emails, known destinations, duplicate records, Gmail draft lifecycle logs, and profile-change history, with preview-first import, exact restore phrase, restore reason, automatic pre-restore backup, `/api/backup/status`, and latest-backup reminders before high-risk local edits.
- LegalPDF Integration Preview panel plus `/api/integration/import-preview`, `/api/integration/import-report`, `/api/integration/checklist`, and `/api/integration/import-plan`, which compare backup contents, optional profile mappings, and court-email differences with `write_allowed: false`, optionally export a private Markdown/JSON preview report under `output/integration-reports/`, produce a read-only checklist of future adapter tasks, and build a read-only adapter import plan that blocks destructive profile or recipient changes before applying anything.
- Read-only LegalPDF adapter contract at `/api/integration/adapter-contract`, documented in `docs/legalpdf-adapter-contract.md`, defining the future caller sequence from source/review through preflight, prepare, Manual Draft Handoff, and local draft recording without writing to LegalPDF Translate or adding Gmail send behavior.
- Write-confirmed LegalPDF adapter apply prototype at `/api/integration/apply-import-plan`, limited to reviewed, non-blocked local Honorários reference changes, requiring `confirm_apply=true`, the exact phrase `APPLY LEGALPDF IMPORT PLAN`, an apply reason, a pre-apply backup, and a private apply report; it never writes to LegalPDF Translate and never invokes Gmail.
- LegalPDF Apply History panel plus `/api/integration/apply-history`, `/api/integration/apply-detail`, `/api/integration/apply-restore-plan`, and guarded `/api/integration/apply-restore`, which list summary-only guarded apply reports, load redacted hash/status comparisons, preview hash-only restore actions, and, with the exact phrase `RESTORE LEGALPDF APPLY BACKUP`, restore only touched local profile/email records from the pre-apply backup after writing a pre-restore backup and private restore report. These paths never expose the full import plan, source backup payload, or raw before/after reference values, and never touch LegalPDF Translate or Gmail.
- Public GitHub Readiness safety gates in the app and CLI: `scripts/public_repo_gate.py` checks staged/tracked Git content for blocked runtime paths and sensitive patterns, while `scripts/public_release_gate.py` remains available for stricter full-tree sanitized-candidate audits.
- Sanitized public-candidate builder in the app and CLI (`scripts/build_public_candidate.py`) that copies only publishable source/doc files, replaces real local data with synthetic fixtures, and reruns the full privacy gate against the candidate tree.
- Generated public-candidate smoke tests for LegalPDF-style workflow landmarks, draft-only reference status, secret-free Google Photos status, read-only LegalPDF preview/report/checklist/import-plan APIs, and the privacy gate.
- Optional local live-app smoke runner (`scripts/local_app_smoke.py`) for checking the running private app's LegalPDF-style landmarks, `Suggested Next Step` surface, draft-only endpoints, secret-free Google Photos status, and public-readiness endpoint without creating PDFs or Gmail drafts by default.
- Local Diagnostics panel in the browser app, listing the safe live smoke, source-upload smoke, supporting-attachment smoke, isolated source-upload smoke, isolated supporting-attachment smoke, isolated LegalPDF adapter contract smoke, advanced/future isolated fake-Gmail Draft API smoke, Browser/IAB review smoke, Browser/IAB upload smoke, Browser/IAB attachment smoke, Browser/IAB profile proposal smoke, Browser/IAB Recent Work lifecycle smoke, Browser/IAB Manual Draft Handoff stale smoke, and Browser/IAB fake Gmail API smoke commands without running shell commands or touching real Gmail.
- Isolated LegalPDF adapter contract smoke in `scripts/isolated_app_smoke.py --adapter-contract-checks`, exercising the future caller sequence through source upload, numbered-answer review recovery, packet preflight, prepare, Manual Draft Handoff, stale prepared-review rejection, and synthetic local draft recording in a disposable runtime.
- Browser/IAB profile-proposal smoke (`--browser-profile-proposal`) that verifies a synthetic unknown recurring pattern surfaces `Profile proposal`, previews the proposed Service profile in the guarded editor, checks LegalPDF import apply gates, and resets without saving profiles, preparing PDFs, recording drafts, or calling Gmail.
- Browser/IAB Manual Draft Handoff stale smoke (`--browser-manual-handoff-stale`) that runs against an isolated synthetic runtime, prepares a disposable replacement payload, builds the copy-ready handoff packet, edits the intake source text, and verifies the packet plus record-helper actions are cleared before any draft can be recorded.
- Hardened Gmail Draft API reconciliation: `/api/gmail/drafts/create` reloads the prepared payload, revalidates draft-only attachments, blocks active drafted/sent duplicates before contacting Gmail, allows replacements only with `supersedes` and a correction reason, and returns a structured confirmation with draft IDs, attachment hashes, and duplicate records created.
- Optional read-only Gmail draft-existence verification: `/api/gmail/drafts/verify` calls only Gmail `users.drafts.get`, reports whether a draft ID still exists plus safe message/thread/recipient metadata, and never writes Gmail, duplicate-index records, draft logs, or reference data. Recent Work exposes the same read-only check for draft rows and keeps manual sent-status updates as local-only lifecycle bookkeeping.
- API-level source upload smoke (`--source-upload-checks`) that posts disposable synthetic photo/PDF sources to `/api/sources/upload` and verifies Source Evidence, recovered PDF candidate fields, Review Attention, and `send_allowed: false` without requiring Python Playwright, preparing PDFs, recording drafts, or calling Gmail.
- API-level supporting attachment smoke (`--supporting-attachment-checks`) that posts a disposable synthetic declaration/proof PDF to `/api/attachments/upload` and verifies the response remains attachment evidence only, with no recovered intake, PDF preparation, draft payload, Gmail args, or send-capable behavior.
- Isolated supporting attachment smoke (`scripts/isolated_app_smoke.py --supporting-attachment-checks --json`) that runs the same declaration/proof evidence check in a temporary synthetic runtime so private source-upload folders stay untouched.
- Opt-in interaction smoke mode (`--interaction-checks`) that exercises profile intake, active-draft checking, packet-mode prepare, attachment-array validation, and underlying-request duplicate-tracking contract through injected test hooks or disposable local state while still requiring `send_allowed: false` throughout.
- Opt-in browser click-through smoke (`--browser-click-through`) that opens the app in a real browser driver when available, verifies the profile-to-review-drawer path, adds a reviewed request to the batch queue, and runs the non-writing batch preflight without clicking artifact-writing prepare or recording drafts by default.
- Optional browser upload/correction smoke flags (`--browser-upload-photo`, `--browser-upload-pdf`, `--browser-upload-supporting-attachment`, and `--browser-correction-mode`) that verify local Source Evidence, Supporting proof/declarations, and draft-lifecycle UI with disposable synthetic files while still blocking prepare, record, and draft-status endpoints by default.
- Opt-in artifact-writing browser replacement smoke (`--browser-prepare-replacement` with `--browser-correction-mode`) that exercises the replacement-draft prepare button against disposable/synthetic active-draft state while still blocking draft recording/status endpoints and all Gmail actions.
- Browser record-helper smoke (`--browser-record-helper` after a prepared replacement or packet payload) that parses fake Gmail `_create_draft` IDs, proves the one-click local recorder stays gated until the Gmail handoff checklist is reviewed, and autofills the local record form without clicking record/status endpoints or Gmail.
- Isolated synthetic runtime support for artifact-writing smoke: `honorarios_app.web --runtime-root ... --init-synthetic-runtime` and `scripts/isolated_app_smoke.py` keep synthetic config, reference data, duplicate/draft logs, PDFs, payloads, manifests, and previews out of the real private workspace state.
- Browser/IAB-native smoke runner (`scripts/browser_iab_smoke.mjs`) for Codex's in-app Browser runtime, importable from the Node REPL, covering the LegalPDF shell, disposable photo/PDF/supporting-attachment upload evidence when safe file-input support is available, review drawer, numbered missing-info answers, batch queue, non-writing batch preflight, stale packet-mode gating, guarded profile proposals, isolated Recent Work lifecycle controls, isolated fake-Gmail draft creation plus read-only verification, correction mode, isolated replacement prepare, Manual Draft Handoff stale clearing, record-helper checklist gating/autofill, workspace reset cleanup, and read-only LegalPDF Apply History/Detail/Restore Plan plus guarded restore-control checks without relying on optional Python Playwright.

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
- Gmail handling stays draft-only. Manual Draft Handoff is always available as the safe fallback, and the optional Gmail Draft API path may create reviewed drafts through Gmail `users.drafts.create` when OAuth is connected. No send action should be added to the UI.

## Public Repository

The public repository is live at:

<https://github.com/Adel199223/honorarios-interpreting>

The root workspace is now the public Git checkout. Real runtime data, personal profiles, draft logs, duplicate history, generated artifacts, and tokens stay in ignored local overlays. Public commits are protected by `.githooks/pre-commit`, which runs `python scripts/public_repo_gate.py --staged`.

## Next Stages

1. Keep hardening the Browser/IAB and isolated smoke runners around any new UI surface, with capability blockers for optional browser features rather than unsafe fallbacks.
2. Use the executable adapter-contract smoke as the starting point for a later LegalPDF caller shim, keeping LegalPDF read-only until the standalone workflow is stable in daily use.
3. Keep read-only Gmail draft reconciliation hardened around real app-created draft IDs as daily use reveals mismatch cases; verification must remain `users.drafts.get` only and must never mutate Gmail, duplicate records, or draft logs.
4. For future public updates, stage files explicitly, run `scripts/public_repo_gate.py --staged` and `--tracked`, and push from the root repo only after tests pass. Rebuild `output/public-candidate` when a separate sanitized audit/export tree is useful.

## Public GitHub Readiness

Public GitHub is enabled for tracked source files in the current root repo. The safety boundary is two-layered:

- `scripts/public_repo_gate.py --staged` and `--tracked` inspect Git content that can be committed or pushed. They block private paths such as local configs, draft logs, duplicate indexes, generated artifacts, real court emails, personal data, tokens, and local-machine paths.
- `scripts/public_release_gate.py --root output/public-candidate --json` scans a full sanitized candidate tree. It may be blocked on the live root because ignored private overlays are intentionally still present on disk.

Use the browser Public GitHub Readiness panel to check tracked Git safety and to build an optional sanitized candidate. A blocked full-workspace privacy result in the live checkout is expected unless all private overlays are absent.

## Non-Negotiable Safety Rules

- Never call Gmail send actions from the app.
- Never treat a closing/signature date as the service date.
- Never generate for translation/word-count sources.
- Never ignore `drafted` duplicate records.
- Never publish real PDFs, Gmail IDs, personal profile/payment data, or real case history.
