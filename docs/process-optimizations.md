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
- `scripts/prepare_honorarios.py` blocks a case/date that already has an active local Gmail draft log entry unless `--allow-existing-draft` is used intentionally.
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

The log lives in:

```text
data/gmail-draft-log.json
```

The log should show active, superseded, trashed, or not-found drafts. Corrections should create a new draft first, then mark and trash the old one after verifying the message ID.

## Similar Photo Cases

For photographed notices like the GNR Cuba pair:

- Put every case from the same photo batch into intake JSON first.
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
