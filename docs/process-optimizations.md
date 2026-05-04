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

In the browser app, use Batch Queue for the same workflow: review each request, add ready requests to the queue, then click `Prepare batch package`. This calls the same multi-intake `/api/prepare` path, so same-batch duplicates, active drafts, date conflicts, missing numbered questions, and recipient mismatches are checked before any PDF or draft payload is written.

When the Review drawer shows missing numbered questions, paste compact answers in the `Numbered answers` card, such as `1. 39` or `2. Beja`, then click `Apply numbered answers`. The app maps those answers back to the current intake fields, reruns the same review endpoint, and keeps generation blocked until duplicate checks, date-conflict rules, and recipient validation are clean. This avoids recreating JSON or re-uploading the source just to fill one missing city, date, or kilometer value.

Use the `Next Safe Action` card as the daily workflow guide. It is computed from the same review/preflight responses as the backend, so it should say whether to answer numbered questions, set aside a translation source, stop for a duplicate, enter correction mode, prepare the PDF, or review Gmail `_create_draft` arguments before recording IDs.

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

Profiles live in `data/service-profiles.json` and fill stable defaults such as payment entity, recipient, service place wording, transport destination, kilometers, and closing city. This keeps repeated Ferreira/PJ, Beja/PJ, Beja medical-legal, Beringel/GNR, Ferreira/GNR, Serpa/GNR, labor-court, and Cuba/GNR cases from requiring hand-built JSON every time.

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

Use `scripts/record_gmail_draft.py` after `_create_draft` returns. Prefer the payload-based form:

```powershell
python scripts/record_gmail_draft.py --payload <payload-json> --draft-id <draft-id> --message-id <message-id> --thread-id <thread-id>
```

In the browser app, paste the returned Gmail connector response and click `Record parsed response + prepared payload`. This removes the easiest-to-fumble parts of recording: copying three Gmail IDs correctly, picking the right packet or individual payload path, and remembering the final local record click, especially after a correction or same-day packet.

The log lives in:

```text
data/gmail-draft-log.json
```

The log should show active, superseded, trashed, or not-found drafts. Corrections should create a new draft first, then mark and trash the old one after verifying the message ID.

## Local Backup State

Use the browser app's References -> Local Backup panel before large edits, machine moves, or future LegalPDF integration work. The backup covers only local app state that needs to travel with the workflow: service profiles, court email aliases, known destinations/kilometers, duplicate-index records, Gmail draft lifecycle records, and profile-change history. It deliberately excludes generated PDFs, source screenshots, Gmail tokens, OpenAI keys, and personal payment/profile config.

`Export backup` writes a private JSON file under `output/backups/` and displays the same JSON for copying. Import is preview-first: paste JSON, run `Preview backup import`, confirm the restore checkbox, then use `Restore backup after preview`. The restore endpoint writes a pre-restore backup before replacing any managed JSON file, so a mistaken restore has a local rollback source.

The app also exposes `/api/backup/status` and renders a `Latest backup` reminder in References. If there is no local backup, or the newest backup is older than 24 hours, the UI warns before saving service profiles, court email records, known destinations, profile rollbacks, or backup restores. The warning is non-send-capable and does not call Gmail; it is only a local safety prompt to export a fresh private backup first.

For LegalPDF reintegration planning, use the separate LegalPDF Integration Preview panel. It compares a backup-like JSON against current profiles and court-email aliases, applies optional profile mapping lines, and reports create/update/unchanged rows with `write_allowed: false`. The `Build integration checklist` action turns those rows into concrete future adapter tasks without writing local reference data. The `Build adapter import plan` action adds merge-policy labels and blockers for destructive profile updates, synthetic/test recipients, and real-recipient drift; it still has `apply_endpoint_available: false`. The `Export preview report` action writes private Markdown and JSON files under `output/integration-reports/` for later review. These actions are deliberately not restore buttons.

## Similar Photo Cases

For photographed notices like the GNR Cuba pair:

- Put every case from the same photo batch into intake JSON first.
- Leave the upload profile on `Auto-detect profile` unless you intentionally want an override. The app now scores recovered source text plus OpenAI evidence locally and auto-applies high-confidence matches such as PJ/GNR Beja, PJ/GNR Ferreira, GNR Serpa, GNR Beringel, and Beja Trabalho. The decision is shown in Source Evidence so wrong-payment-recipient risks are reviewable before PDF generation.
- Use the Source Evidence `Recovered Fields` ledger to see where each autofilled value came from: deterministic text, OpenAI OCR, image metadata, known-destination data, or a service-profile default. The confidence/status chips are review evidence only; they never bypass duplicate checks, date-conflict questions, recipient validation, or draft-only safeguards.
- If Source Evidence shows a `Profile proposal`, use `Preview proposed profile` to load it into the guarded profile editor. Save it only after checking the recipient, kilometers, addressee, and service-place phrase; the proposal never writes reference data by itself.
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

Use `--browser-click-through` when you want a real browser to verify the profile-to-review-drawer path and batch queue without preparing artifacts:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --json
```

This check deliberately stops before `Prepare batch package`, `Record draft`, and any Gmail action. It also verifies the `Next Safe Action` surface in the review drawer. It can report a blocker if Python Playwright is unavailable; that is a tooling blocker, not a Gmail workflow failure.

To cover the local upload and correction surfaces without creating PDFs or recording drafts, add the browser UI-only flags:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-upload-photo --browser-upload-pdf --browser-correction-mode --json
```

This creates disposable synthetic upload files, verifies the Source Evidence card and recovered PDF candidate fields, checks the draft lifecycle/correction reason surface, and still blocks prepare, record, and draft-status POSTs. The app may store synthetic source-preview artifacts from the upload, but it must not create PDF/draft payloads or Gmail draft-log records in this mode.

To cover replacement-draft preparation itself, use the opt-in artifact-writing flag only against disposable/synthetic state with an existing active draft blocker:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-correction-mode --browser-prepare-replacement --json
```

This exercises the `Prepare replacement draft` button and allows `/api/prepare`, so it may create local PDF and draft-payload artifacts. It still blocks `/api/drafts/record` and `/api/drafts/status`, does not call Gmail, and does not record draft IDs.

The safer version is the isolated smoke launcher, which creates a temporary runtime with synthetic config, reference data, duplicate index, draft log, and output folders:

```powershell
python scripts/isolated_app_smoke.py --interaction-checks --json
```

For replacement smoke, the isolated launcher can seed a synthetic active draft and target that case:

```powershell
python scripts/isolated_app_smoke.py --browser-click-through --browser-correction-mode --browser-prepare-replacement --json
```

The isolated launcher never writes to the real `data/`, `output/`, or `tmp/` folders. Browser click-through still depends on optional Python Playwright; when it is unavailable, the smoke reports that as a tooling blocker rather than falling back to unsafe real-state checks.

For disposable or synthetic state, add `--interaction-checks` to exercise profile intake, active-draft checking, and packet-mode prepare in one pass:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --interaction-checks --json
```

The interaction mode validates that the prepared packet exposes `gmail_create_draft_args.attachment_files` as an array and includes `underlying_requests` for duplicate protection. It may create local PDF/draft payload artifacts on a real app, but it never calls Gmail and fails if any response exposes a non-false `send_allowed` value.
