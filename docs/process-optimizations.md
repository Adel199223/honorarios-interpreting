# Process Optimizations

These notes capture what was improved after preparing the two photographed GNR Cuba cases.

## What Was Inefficient

- The old workflow required separate commands for duplicate checks, PDF generation, PDF rendering, draft payload creation, Gmail draft creation, and draft cleanup.
- Recipient/payment mappings were reviewed one draft at a time instead of side by side.
- Gmail draft IDs were not stored locally after `_create_draft`, making corrections depend on memory and manual draft-list checks.
- Date conflicts were handled by PDF generation, but duplicate checking and numbered questions did not surface every conflict early enough.

## New Default Workflow

Use one local preflight command for complete intakes:

```powershell
python scripts/prepare_honorarios.py <intake-json> [<intake-json> ...] --render-previews
```

In the browser app, use Batch Queue for the same workflow: review each request, add ready requests to the queue, then click `Check batch preflight`. This calls `/api/prepare/preflight`, validates same-batch duplicates, active drafts, date conflicts, missing numbered questions, additional-attachment email-body rules, and packet recipient mismatches without writing PDFs, draft payloads, intake JSON, or manifests. Only after that non-writing check is clean and still matches the current queue should you click `Prepare batch package`, which calls the artifact-writing `/api/prepare` path. If you add, remove, reorder, clear, or toggle packet mode after preflight, the browser marks that preflight stale and keeps preparation gated until you run it again.

When the Review drawer shows missing numbered questions, paste compact answers in the `Numbered answers` card, such as `1. 39` or `2. Beja`, then click `Apply numbered answers`. The app maps those answers back to the current intake fields, reruns the same review endpoint, and keeps generation blocked until duplicate checks, date-conflict rules, and recipient validation are clean. This avoids recreating JSON or re-uploading the source just to fill one missing city, date, or kilometer value.

Use the intake drop zone for local screenshots/photos/PDFs when you want the fastest path from a saved or copied source file to Source Evidence. Dropped or pasted files are only classified as notification PDF or photo/screenshot and sent through the existing `/api/sources/upload` review path; dropping or pasting a file never prepares a PDF, records a draft, or calls Gmail by itself.

Use `Supporting proof / declarations` when a job has a declaration or proof image/PDF that should travel with the final Gmail draft. The app validates those files as PDF/image only, stores them under the local source artifact root, adds their absolute paths to `additional_attachment_files`, and inserts the custom email body that mentions the documento(s) comprovativo(s). Multi-file drag/drop treats the first file as the source and any extra files as supporting proof, still without preparing PDFs, recording drafts, or calling Gmail.

Use the `Suggested Next Step` card as the daily workflow guide. It is computed from the same review/preflight responses as the backend. It is not a separate task; it should explain why the app paused, what is allowed now, and whether to answer numbered questions, set aside a translation source, stop for a duplicate, enter correction mode, prepare the PDF, or review Gmail `_create_draft` arguments before recording IDs.

Use the left-sidebar `Reset workspace` button when you want to clear the visible browser state and start fresh. It resets the current intake form, upload forms, prepared payload preview, correction fields, draft lifecycle card, and Batch Queue. It does not delete generated PDFs, draft payload files, duplicate-index records, draft-log records, reference data, or Gmail drafts. If the topbar says the local server is disconnected or stale, restart the app and reload before continuing; the banner blocks prepare, Gmail, upload, record, status, and reference-write actions, while `Reset workspace` remains available for clearing only client-side state.

If the queued requests should be sent together, enable `Packet mode` before preparing. Packet mode is still draft-only: it requires one shared recipient, builds the individual PDFs, combines the PDFs and any already-declared supporting attachments into one packet PDF, and makes that packet the only `attachment_files` entry in the Gmail `_create_draft` args. The displayed Batch Queue order is the packet order; drag requests or use `Move up` / `Move down` before preparing when declarations or same-day periods need a specific sequence. Use `Inspect` on each queued row to review the Packet item inspector before generation; it shows the generated requerimento PDF position plus any supporting attachments that will follow that request. The packet payload carries `underlying_requests` so recording the Gmail draft still protects every case/date/period in the duplicate index. The prepared packet result includes a Packet draft recording helper with a copyable `record_gmail_draft.py` command and a JSON object, so the packet draft and all underlying duplicate blockers can be logged without retyping paths. The Record Gmail Draft card can parse a pasted Gmail connector response into draft/message/thread IDs, then autofill the latest prepared packet or individual payload path while preserving those IDs. The one-click `Record parsed response + prepared payload` action combines those local steps after `_create_draft` has already returned, so logging a reviewed draft no longer depends on manually clicking three separate buttons.

It performs the local work in this order:

1. Classify every source and set aside translation/word-count requests before asking intake questions.
2. Validate every intake in the batch, including missing numbered questions, strict effective-date validation, duplicates, recipient/payment consistency, attachment readiness, and same-batch duplicates.
3. Generate PDFs only after the whole batch passes validation.
4. Verify PDF text content.
5. Create and validate Gmail draft payloads.
6. Optionally render PNG previews for visual inspection.
7. Write a rich batch manifest for review.

Only after reviewing the manifest should a future assistant call Gmail `_create_draft`.

For familiar service patterns, create the intake first from a reusable profile:

```powershell
python scripts/create_intake.py --profile pj_gnr_ferreira --case-number 86/26.8GAFAL --service-date 2026-02-15
```

Profiles live in local `data/service-profiles.json` and fill stable defaults such as payment entity, recipient, service place wording, transport destination, kilometers, and closing city. Public checkouts fall back to the sanitized `data/service-profiles.example.json` fixture until a local overlay exists. This keeps repeated Ferreira/PJ, Beja/PJ, Beja medical-legal, Beringel/GNR, Ferreira/GNR, Serpa/GNR, labor-court, and Cuba/GNR cases from requiring hand-built JSON every time.

## New Safety Checks

- `scripts/check_duplicate.py` now fails loudly on unconfirmed date conflicts.
- `scripts/intake_questions.py` asks about date conflicts even when `service_date_source` has a non-confirming value such as `document_text`.
- `scripts/build_email_draft.py` rejects invalid explicit recipient fields instead of silently falling back.
- The draft builder rejects known payment-entity/recipient mismatches unless the intake includes `recipient_override_reason`.
- Multiple source court emails are treated as ambiguous.
- Draft payloads include case number, service date, payment entity, service entity, PDF basename, and PDF SHA-256 hash.
- Draft payloads and manifests include `gmail_create_draft_args`, ready to pass to `_create_draft`; `attachment_files` is always an array.
- `scripts/prepare_honorarios.py` blocks a case/date that already has an active local Gmail draft log entry unless `--allow-existing-draft` is used with `--correction-reason "<short reason>"`, matching the browser correction-mode safety rule.
- Active draft blocking is period-aware: same case/date with different `service_period_label` values can coexist, while exact duplicates still block.
- Duplicate matching normalizes leading-zero case numbers and period-label capitalization/spacing.
- Draft payload validation blocks stale payloads before Gmail if attachments are not an array of absolute existing files, if `gmail_create_draft_args` is missing, or if draft-only safety fields are wrong.
- Packet draft payloads can include `underlying_requests`, and recording the draft writes one duplicate blocker for each underlying honorários request.
- Unknown `court_email_key` values fail. Generic `Tribunal de Beja` maps to Beja Ministério Público; labor-court aliases stay specific to `Tribunal do Trabalho de Beja` / `Juízo do Trabalho de Beja`.
- Polícia Judiciária sources require a local host building/city before generation, because PJ often uses a GNR building, hospital, or other local service building rather than its own premises. Inspector names remain optional.

## Gmail Draft State

The browser app now treats Manual Draft Handoff as an always-available daily path, with or without Gmail OAuth. After a prepared PDF and payload are reviewed, use the exact displayed `_create_draft` args, paste the returned draft/message/thread IDs, and record them through the same local draft-log and duplicate-index code. `/api/gmail/status` reports disconnected OAuth as a ready manual mode rather than a setup failure.

The optional local Gmail Draft API connector remains available for direct in-app draft creation. When connected, `Create Gmail Draft` reloads and validates the prepared payload, checks duplicate-index and active draft-log blockers for every underlying request, calls only Gmail `users.drafts.create`, then records the returned IDs automatically. The connector reads ignored `config/gmail.local.json`, stores OAuth tokens in ignored `config/gmail-token.local.json`, and exposes only secret-free readiness through `/api/gmail/status`. If Gmail creation fails, no local draft or duplicate record is written.

Use `scripts/record_gmail_draft.py` after a manual `_create_draft` recovery flow returns. Prefer the payload-based form:

```powershell
python scripts/record_gmail_draft.py --payload <payload-json> --draft-id <draft-id> --message-id <message-id> --thread-id <thread-id>
```

In the browser app, use the Manual Draft Handoff card whenever you prefer the explicit copy/paste recovery path, including when Gmail OAuth is disconnected or when you intentionally use the external `_create_draft` connector. Paste the returned Gmail connector response and click `Record parsed response + prepared payload`. This removes the easiest-to-fumble parts of recording: copying three Gmail IDs correctly, picking the right packet or individual payload path, and remembering the final local record click, especially after a correction or same-day packet. The one-click helper stays disabled until you tick the Gmail handoff checklist confirming that you reviewed the PDF preview and used the exact displayed draft args.

After the draft is actually sent by hand in Gmail, use **Recent Work** to filter to active/drafted rows, set the manual sent date, and click `Mark manually sent` on the matching draft. That action is local bookkeeping only: it updates the draft log and duplicate index to `status: sent` with `sent_date`; it does not call Gmail or alter the message. The neighboring `Verify draft exists` action is read-only Gmail reconciliation through `users.drafts.get` and never writes local records. If that read-only check reports `not_found`, the follow-up `Mark not_found locally` action asks for a reason and the server re-checks Gmail before updating the local lifecycle rows.

The log lives in:

```text
data/gmail-draft-log.json
```

The log should show active, superseded, trashed, or not-found drafts. Corrections should create a new draft first, then mark and trash the old one after verifying the message ID.

## Local Backup State

Use the browser app's References -> Local Backup panel before large edits, machine moves, or future LegalPDF integration work. The backup covers only local app state that needs to travel with the workflow: personal profiles, service profiles, court email aliases, known destinations/kilometers, duplicate-index records, Gmail draft lifecycle records, and profile-change history. It deliberately excludes generated PDFs, source screenshots, Gmail tokens, and OpenAI keys; backup files are private because personal profiles can contain address/payment data.

`Export backup` writes a private JSON file under `output/backups/` and displays the same JSON for copying. Import is preview-first: paste JSON, run `Preview backup import`, confirm the restore checkbox, type the exact phrase `RESTORE LOCAL HONORARIOS BACKUP`, add a short restore reason, then use `Restore backup after preview`. The restore endpoint writes a pre-restore backup before replacing any managed JSON file, so a mistaken restore has a local rollback source.

The app also exposes `/api/backup/status` and renders a `Latest backup` reminder in References. If there is no local backup, or the newest backup is older than 24 hours, the UI warns before saving service profiles, court email records, known destinations, profile rollbacks, or backup restores. The warning is non-send-capable and does not call Gmail; it is only a local safety prompt to export a fresh private backup first.

For LegalPDF reintegration planning, use the separate LegalPDF Integration Preview panel. It compares a backup-like JSON against current profiles and court-email aliases, applies optional profile mapping lines, and reports create/update/unchanged rows with `write_allowed: false`. The `LegalPDF Adapter Contract` link exposes the secret-free, read-only future caller boundary at `/api/integration/adapter-contract`, including the safe sequence from source review through preflight, PDF preparation, Manual Draft Handoff, and local draft recording. The `Build integration checklist` action turns those rows into concrete future adapter tasks without writing local reference data. The `Build adapter import plan` action adds merge-policy labels and blockers for destructive profile updates, synthetic/test recipients, and real-recipient drift. The write-confirmed apply action is deliberately narrow: it requires the exact phrase `APPLY LEGALPDF IMPORT PLAN`, an apply reason, zero blocking tasks, a pre-apply backup, and a private apply report under `output/integration-reports/`; it writes only local Honorários reference data and never touches LegalPDF Translate or Gmail. After an apply, use LegalPDF Apply History to find the private report and pre-apply backup again. Use the Details button only for redacted hash/status comparisons, and the Restore plan button for a hash/status rollback preview. If rollback is needed, the guarded restore requires the exact phrase `RESTORE LEGALPDF APPLY BACKUP`, a restore reason, and a non-blocked restore plan; it writes a pre-restore backup, restores or removes only the touched local profile/email records, writes a private restore report, and still never touches LegalPDF Translate or Gmail. Neither the history, detail, restore-plan, nor restore response exposes the full import plan, source backup payload, or raw before/after profile/email values.

OpenAI OCR/autofill uses the Responses API with a strict JSON Schema named `honorarios_source_recovery`. That schema requires `raw_visible_text`, a fixed `fields` object, `translation_indicators`, and `warnings`, with no extra properties. The prompt is now anchored with the project patterns that caused the most manual corrections: PJ jobs need the local host building/city such as a GNR post, Beringel services can still be paid through Beja, Tribunal do Trabalho de Beja is a specific labor-court path, medical-legal accompaniment should name `Gabinete Médico-Legal de Beja` / `Hospital José Joaquim Fernandes`, and `número de palavras` belongs in translation indicators. Source Evidence shows the schema name, prompt version, fields found, fields not found, and a compact `Review Attention` card, so an upload with weak OCR, source warnings, a date conflict, missing required information, duplicate/active-draft blockers, generic profile fallback, or a profile proposal is easier to spot before generating. The model can make upload review faster, but it remains evidence only: source classification, date-conflict questions, duplicate checks, recipient validation, PDF generation, and Gmail draft-only guards still decide what can happen next.

## Similar Photo Cases

For photographed notices like the GNR Cuba pair:

- Put every case from the same photo batch into intake JSON first.
- Leave the upload profile on `Auto-detect profile` unless you intentionally want an override. The app now scores recovered source text plus OpenAI evidence locally and auto-applies high-confidence matches such as PJ/GNR Beja, PJ/GNR Ferreira, GNR Serpa, GNR Beringel, and Beja Trabalho. The decision is shown in Source Evidence so wrong-payment-recipient risks are reviewable before PDF generation.
- For blank/manual requests, paste any visible source text into `Source text` before review. The same service-profile evidence path now runs during review: high-confidence known patterns can fill safe defaults, and unknown recurring patterns can show a guarded `Profile proposal` without writing reference data.
- Read the Source Evidence `Review Attention` card first. If it says `blocked`, answer the numbered questions, resolve the date conflict, set aside the translation source, or use correction mode before preparing any PDF. If it says `review`, inspect the warning or profile proposal before continuing.
- Use the Source Evidence `Recovered Fields` ledger to see where each autofilled value came from: deterministic text, OpenAI OCR, image metadata, known-destination data, or a service-profile default. The confidence/status chips are review evidence only; they never bypass duplicate checks, date-conflict questions, recipient validation, or draft-only safeguards.
- If you change the uploaded source, apply new review answers, reset the review, or edit the intake form after preparing a PDF, the browser clears the old PDF preview, draft payload path, Gmail record-helper IDs, and draft lifecycle state. This is intentional: prepare again from the current reviewed data instead of reusing stale Gmail args.
- If Source Evidence shows a `Profile proposal`, use `Preview proposed profile` to load it into the guarded profile editor. Save it only after checking the recipient, kilometers, addressee, and service-place phrase; the proposal never writes reference data by itself.
- In References, preview court-email and destination diffs before saving. Recipient addresses and one-way kilometers affect daily requests directly, so their preview endpoints are no-write/no-Gmail and saved edits are recorded in the local change history for audit.
- For sideways, rotated, cropped, or visually awkward screenshots, preserve the source upload and visible Google Photos metadata. The app now passes explicit rotated/cropped/Google Photos instructions to OpenAI recovery, treats compact metadata filenames like `20260415_205459.jpg` as `photo_metadata_date`, and shows crop/partial warnings in Source Evidence.
- For Google Photos items, prefer the OAuth Picker import when private local credentials are configured: connect OAuth, open a Picker session, choose one image, and import the selected item through the normal source-review pipeline. The selected-photo bridge remains available for downloaded images: paste visible metadata/filename/date into the Google Photos metadata box. Do not store or display raw OAuth URLs beyond the short-lived authorization handoff, media IDs, base URLs, tokens, or client secrets in review evidence, logs, draft payloads, or public fixtures.
- Create temporary rotated/cropped inspection images outside the project workspace only when the app and AI evidence still leave the case number or date ambiguous.
- For weak/scanned notification PDFs, let the app render the first pages to source-preview PNGs before AI recovery. If `pdftoppm` is not available, Source Evidence must show that warning and the draft workflow still remains review-only.
- Ask for confirmation only if that enhanced view is still genuinely ambiguous.
- Run one `prepare_honorarios.py` command with all of them.
- Compare the manifest rows before Gmail draft creation.
- Pay special attention to:
  - `case_number`
  - `service_date`
  - `date_conflict`
  - `payment_entity`
  - `service_entity`
  - `recipient`
  - attached PDF path

This makes swapped Cuba/Beja-style mistakes visible before drafts are created.

## Workflow Smoke Checks

Use the default smoke runner for a non-writing live-app check:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --json
```

The default smoke checks `/api/health` before treating a rendered page as usable. If the local server has stopped but the in-app browser still shows an old tab, the smoke reports a clean `endpoint_api_health` blocker instead of clicking prepare, record, upload, or Gmail controls.

The same commands are visible in the app under References -> Local Diagnostics. That panel is read-only: it explains the safest smoke check for the current kind of change and copies commands for PowerShell, including the Python runtime doctor, the read-only LegalPDF adapter readiness command, the isolated supporting-attachment smoke command, the isolated LegalPDF adapter contract smoke command, the advanced/future isolated fake-Gmail Draft API smoke command, the Browser/IAB upload smoke command with disposable photo/PDF flags, the Browser/IAB attachment smoke command for the Supporting proof UI, the Browser/IAB answers/apply smoke command (`--browser-answer-questions --browser-apply-history`), the isolated Browser/IAB record-helper smoke command, the isolated Python Playwright record-helper smoke command, the Browser/IAB profile proposal smoke command, the isolated Browser/IAB Recent Work lifecycle smoke command, the isolated Browser/IAB Recent Work reconciliation smoke command, the isolated Browser/IAB Manual Draft Handoff stale smoke command, and the isolated Browser/IAB fake Gmail API smoke command, but it does not run shell commands, prepare PDFs, record drafts, or call real Gmail. Run `python scripts/runtime_doctor.py --json` first when the local Python path or dependency set is suspect, then run adapter readiness before the isolated adapter smoke; the full adapter smoke then validates the nested Gmail boundary as draft-only and send-disabled before running the synthetic caller sequence.

Use `--browser-click-through` when you want a real browser to verify the profile-to-review-drawer path and batch queue without preparing artifacts:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --json
```

This check deliberately stops before artifact-writing preparation, `Record draft`, and any Gmail action. It also verifies the `Suggested Next Step` surface in the review drawer and the browser `Check batch preflight` card. It can report a blocker if Python Playwright is unavailable; that is a tooling blocker, not a Gmail workflow failure.

Successful browser smoke checks finish by resetting the workspace, so synthetic smoke cases and queued test requests are cleared from the open browser tab. The Python browser smoke clicks `Reset workspace`; the Browser/IAB runner verifies that control is present and then reloads the local app because the IAB adapter can be inconsistent with sidebar link activation.

When working inside Codex with the Browser plugin, use the Browser/IAB runner instead of optional Python Playwright for the normal review/batch path. The Python smoke command can print the exact Node REPL handoff cell:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-iab-click-through --browser-answer-questions --json
```

For disposable Browser/IAB coverage of the numbered-answer loop plus LegalPDF Apply History, use the isolated launcher:

```powershell
python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-answer-questions --browser-apply-history --json
```

Raw shell subprocesses cannot drive the Codex in-app Browser runtime, so that command reports a short blocker with `details.node_repl_cell`. Paste that cell into the Codex Node REPL Browser surface, or import the runner directly there:

```javascript
const { runBrowserIabSmoke } = await import('file:///<project-root>/scripts/browser_iab_smoke.mjs?run=' + Date.now());
const result = await runBrowserIabSmoke({
  baseUrl: 'http://127.0.0.1:8765',
  profile: 'gnr_serpa_judicial',
  caseNumber: '999/26.0IAB',
  serviceDate: '2026-05-04',
  answerQuestions: true,
  applyHistory: true
});
nodeRepl.write(JSON.stringify(result, null, 2));
```

This Browser/IAB path opens a fresh in-app tab, checks the LegalPDF-style shell, opens the review drawer, can intentionally leave one required field blank and apply a compact numbered answer, confirms draft-only review evidence, adds the reviewed request to the batch queue, runs the non-writing batch preflight, resets the temporary workspace by reloading the local app, and, when `applyHistory: true` is set, verifies References -> LegalPDF Apply History plus the read-only Detail/Restore Plan surfaces and guarded restore confirmation controls without preparing PDFs, writing reference files, recording drafts, or calling Gmail.

When `uploadPhoto: true`, `uploadPdf: true`, or `uploadSupportingAttachment: true` is passed to `runBrowserIabSmoke`, the runner creates disposable synthetic files, uses the Browser runtime's guarded `setInputFiles` path, verifies Source Evidence, recovered PDF candidate fields, and/or the Supporting proof/declarations list, and still stops before prepare, draft recording, draft status changes, or Gmail. If the Browser adapter cannot set local file inputs, that step should return a tooling blocker instead of using real private files.

When `profileProposal: true` is passed to `runBrowserIabSmoke`, the runner uses a disposable unknown GNR/MP pattern to verify that Source Evidence shows `Profile proposal`, clicks `Preview proposed profile`, checks the guarded Service profile editor fields, previews the profile change, and verifies the LegalPDF import apply controls are still confirmation-gated. This is the recommended non-Gmail confidence check before LegalPDF adapter work because it proves new recurring patterns can be suggested without writing reference data.

To cover upload recovery and `Review Attention` even when Python Playwright is not installed, use the API-level source upload smoke:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --source-upload-checks --json
```

This posts disposable synthetic photo and notification-PDF sources directly to `/api/sources/upload`, checks Source Evidence, recovered PDF candidate fields, `Review Attention`, and `send_allowed: false`, and never calls prepare, draft recording/status, or Gmail. Use `python scripts/isolated_app_smoke.py --source-upload-checks --json` when you want the synthetic source-preview artifacts to live only in a temporary runtime.

To cover declaration/proof upload safety after attachment-related changes, use the API-level supporting attachment smoke:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --supporting-attachment-checks --json
```

This posts a disposable synthetic declaration/proof PDF directly to `/api/attachments/upload`, checks the response is supporting-attachment evidence only, and verifies no recovered intake, PDF preparation, draft payload, or Gmail draft args are exposed.

Use `python scripts/isolated_app_smoke.py --supporting-attachment-checks --json` when you want the same declaration/proof check to run inside a temporary synthetic runtime, keeping private source-upload folders untouched.

To cover the real browser Supporting proof / declarations UI path, use the Browser/IAB attachment smoke:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-iab-click-through --browser-upload-supporting-attachment --json
```

The shell command returns the Node REPL handoff cell. When run through the Codex Browser runtime, it uploads `synthetic-declaracao.pdf`, checks the supporting attachment list and email-body reminder, and still blocks prepare, draft recording, draft-status writes, and Gmail.

To cover the guarded profile-proposal path from PowerShell, use:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-iab-click-through --browser-profile-proposal --json
```

The shell command returns the Node REPL handoff cell. When run through the Codex Browser runtime, it previews a synthetic proposed profile in the Service profiles editor, checks the LegalPDF apply phrase/reason controls, and resets the workspace without saving profiles, preparing PDFs, recording drafts, or calling Gmail.

To cover the connected-Gmail browser controls without touching real Gmail, use the isolated fake-Gmail Browser/IAB smoke:

```powershell
python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-gmail-api-create --json
```

The isolated launcher enables fake Gmail only in the temporary runtime. The Browser/IAB runner prepares a synthetic PDF payload, clicks `Create Gmail Draft`, verifies the deterministic fake `draft-smoke-*` ID, then clicks the read-only `Verify created draft` shortcut and confirms the `users.drafts.get` reconciliation panel. It must not be run against the private live app unless fake Gmail mode is intentionally active in an isolated runtime.

To cover the Manual Draft Handoff stale-state path after a prepared replacement payload, use the isolated Browser/IAB handoff stale smoke:

```powershell
python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-correction-mode --browser-prepare-replacement --browser-manual-handoff-stale --json
```

The isolated launcher seeds a synthetic active draft, prepares a disposable replacement, builds the copy-ready Manual Draft Handoff packet, then changes the intake source text. The Browser/IAB runner verifies the handoff packet is hidden again, the copy/record helpers are disabled, and the prepared result is marked stale. It never records drafts and never calls Gmail.

To cover the Recent Work lifecycle controls without touching real history or Gmail, use the isolated Browser/IAB lifecycle smoke:

```powershell
python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-recent-work-lifecycle --json
```

The isolated launcher seeds a synthetic active draft, opens Recent Work, checks lifecycle filters plus `Verify draft exists` and `Mark manually sent` controls, and deliberately does not click those row actions.

To cover Recent Work read-only Gmail reconciliation, use the isolated fake-Gmail Browser/IAB smoke:

```powershell
python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-recent-work-reconciliation --json
```

That path seeds a synthetic draft ID that fake Gmail reports as missing, clicks only `Verify draft exists`, confirms the `users.drafts.get` `not_found` result, and does not click `Mark not_found locally` or any local status-write action.

If the Browser/IAB smoke has prepared a disposable replacement or packet payload, add `--browser-record-helper` to check the final local handoff surface. This parses fake `_create_draft` IDs and clicks `Autofill from prepared payload`, then verifies the record form values; it must not click `Record parsed response + prepared payload`, `Record draft`, `/api/drafts/record`, `/api/drafts/status`, or Gmail.

To cover the local upload and correction surfaces without creating PDFs or recording drafts, add the browser UI-only flags:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-upload-photo --browser-upload-pdf --browser-upload-supporting-attachment --browser-correction-mode --json
```

This creates disposable synthetic upload files, verifies the Source Evidence card, recovered PDF candidate fields, and optional supporting-attachment list, checks the draft lifecycle/correction reason surface, and still blocks prepare, record, and draft-status POSTs. Python Playwright drives this path when installed; Browser/IAB can now attempt the same upload evidence via safe `setInputFiles` and report a clean tooling blocker if the in-app adapter lacks that capability. The app may store synthetic source-preview or supporting-attachment artifacts from the upload, but it must not create PDF/draft payloads or Gmail draft-log records in this mode.

To cover replacement-draft preparation itself, use the opt-in artifact-writing flag only against disposable/synthetic state with an existing active draft blocker:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-correction-mode --browser-prepare-replacement --json
```

This exercises the `Prepare replacement draft` button and allows `/api/prepare`, so it may create local PDF and draft-payload artifacts. It still blocks `/api/drafts/record` and `/api/drafts/status`, does not call Gmail, and does not record draft IDs.

For the same replacement-plus-record-helper path in a disposable runtime, use:

```powershell
python scripts/isolated_app_smoke.py --browser-click-through --browser-iab-click-through --browser-correction-mode --browser-prepare-replacement --browser-record-helper --json
```

The safer version is the isolated smoke launcher, which creates a temporary runtime with synthetic config, reference data, duplicate index, draft log, and output folders:

```powershell
python scripts/isolated_app_smoke.py --interaction-checks --json
```

For replacement smoke, the isolated launcher can seed a synthetic active draft and target that case:

```powershell
python scripts/isolated_app_smoke.py --browser-click-through --browser-correction-mode --browser-prepare-replacement --json
```

The isolated launcher never writes to the real `data/`, `output/`, or `tmp/` folders. Browser click-through still depends on optional Python Playwright; when it is unavailable, the smoke reports that as a tooling blocker rather than falling back to unsafe real-state checks.

For Browser/IAB replacement checks, start an isolated synthetic app with a seeded active draft, then run the same importable IAB runner from the Codex Node REPL:

```powershell
python -m honorarios_app.web --host 127.0.0.1 --port 8769 --runtime-root <temp-runtime> --init-synthetic-runtime --seed-active-draft
```

```javascript
const { runBrowserIabSmoke } = await import('file:///<project-root>/scripts/browser_iab_smoke.mjs?run=' + Date.now());
const result = await runBrowserIabSmoke({
  baseUrl: 'http://127.0.0.1:8769',
  profile: 'example_interpreting',
  caseNumber: '999/26.0REPL',
  serviceDate: '2026-05-04',
  correctionMode: true,
  prepareReplacement: true,
  correctionReason: 'synthetic replacement check'
});
nodeRepl.write(JSON.stringify(result, null, 2));
```

That version may create isolated PDF/payload artifacts under the temporary runtime, but it still never records drafts, changes draft statuses, or calls Gmail.

For disposable or synthetic state, add `--interaction-checks` to exercise profile intake, active-draft checking, and packet-mode prepare in one pass:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --interaction-checks --json
```

The interaction mode validates that the prepared packet exposes `gmail_create_draft_args.attachment_files` as an array and includes `underlying_requests` for duplicate protection. It may create local PDF/draft payload artifacts on a real app, but it never calls Gmail and fails if any response exposes a non-false `send_allowed` value.
