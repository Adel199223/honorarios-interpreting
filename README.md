# Honorários Interpreting PDF Project

This project helps create Portuguese `requerimento de honorários` PDFs for in-person interpreting services.

It is built from the confirmed interpreting honorários PDFs sent between 2026-02-02 and 2026-05-02. It deliberately excludes translation/word-count requests.

## Quick Start

### Local Browser App

This project now includes a local-first browser app inspired by the LegalPDF Translate interpretation workflow, while keeping this project's PDF-only generator, duplicate checks, and Gmail draft safety rules as the source of truth.

Install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

Start the app:

```powershell
python -m honorarios_app.web --host 127.0.0.1 --port 8765
```

Then open:

`http://127.0.0.1:8765`

The app supports the main workflow:

- upload a local notification PDF or photo/screenshot
- import a selected/downloaded Google Photos image through the local photo path, with pasted visible filename/date metadata
- connect Google Photos OAuth Picker when private local credentials are configured, choose one photo, and import it through the same review pipeline
- use OpenAI OCR/autofill when `OPENAI_API_KEY` or ignored `config/ai.local.json` is configured
- auto-detect the best service profile from local evidence when you upload a source, while still showing the profile decision for review
- propose a guarded reusable service profile when a new upload looks like a recurring pattern that does not match existing profiles
- create an intake from a known service profile
- show a `Next Safe Action` card that points to the safest next step after each review or preparation result
- review the Portuguese draft text before generating the PDF
- queue multiple reviewed requests, run a non-writing batch preflight, and prepare a batch package only after the queue is clean
- enable Packet mode for a batch when several requerimentos should become one combined PDF attachment
- show numbered missing-information questions
- apply short numbered answers directly in the review drawer, then re-run the same review without rebuilding the intake manually
- block translation/word-count requests
- warn about duplicate `sent` or `drafted` case/date records
- generate the PDF and Gmail `_create_draft` payload
- record returned Gmail draft IDs so duplicates are protected immediately
- parse a pasted Gmail `_create_draft` response to fill the draft/message/thread ID fields locally
- autofill the Record Gmail Draft form from the prepared packet or individual payload while preserving pasted Gmail draft/message/thread IDs
- record the parsed Gmail response and latest prepared payload in one local-only step after the draft is created externally
- handle corrections by checking active drafts, preparing replacement drafts only with a reason, and marking older draft records as superseded/trashed without deleting history
- filter Recent Work by lifecycle state (`active`, `drafted`, `sent`, `superseded`, `trashed`, `not_found`) to separate current duplicate blockers from audit history
- reset the current browser workspace when a test or old review leaves synthetic fields, prepared payloads, or queued requests on screen
- maintain known destinations/kilometers and court email aliases from the References screen
- maintain guarded service profiles with recipient validation, profile diffs, local change history, safe rollback, and a sample Portuguese draft preview
- export and restore private local backups for reference data, duplicate records, and draft lifecycle logs
- run a local Public GitHub Readiness privacy gate before any public publishing attempt
- build a read-only LegalPDF adapter import plan that flags destructive profile or recipient changes
- apply a reviewed, non-blocked LegalPDF import plan only after explicit confirmation, with a pre-apply backup and private apply report

Service profile edits are guarded because they affect legal wording, payment entities, and recipient logic. The browser app validates the profile, checks recipient consistency against the court email directory, shows a sample draft preview, and records a local profile-change log after saving. Use the preview button when you want to inspect the diff without writing anything. Profile rollbacks must also be previewed first; they are blocked if the current profile no longer matches the selected change log entry.

The browser app does not send email. It prepares connector-ready Gmail draft arguments only.

To smoke-check the running local app without creating PDFs or Gmail drafts:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --json
```

The smoke runner checks the LegalPDF-style workflow landmarks, the `Next Safe Action` guidance surface, draft-only Gmail contract, Google Photos/AI status endpoints, local diagnostics status, and public-readiness endpoint. It fails if send-capable Gmail copy such as `_send_email` or `_send_draft` appears on the homepage.

For a real browser review-flow click-through, use the opt-in browser smoke:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --json
```

This opens the app, creates a synthetic reviewed request from a profile, verifies the review drawer and `Next Safe Action` card, adds it to the batch queue, and runs the non-writing `Check batch preflight` action. By default it does not click prepare, record drafts, or call Gmail. If Python Playwright is not installed, the check reports a clean blocker instead of crashing. The deeper `--browser-prepare-packet` and `--browser-prepare-replacement` options are for disposable/synthetic state only because they can create local PDF/payload artifacts.

Browser smoke checks now reset the workspace at the end of a successful run, so synthetic values such as `999/26.0SMOKE` and queued test requests do not linger in the open app tab. Python browser smoke clicks `Reset workspace`; the Browser/IAB smoke verifies that control and then reloads the local app as a safer adapter-compatible reset. You can also click `Reset workspace` yourself in the left sidebar when you want a clean New Job surface without changing any real duplicate records, draft logs, generated PDFs, or Gmail state.

Inside Codex, prefer the Browser/IAB path for the live LegalPDF-style UI. It can also verify the numbered missing-info answer loop and the References -> LegalPDF Apply History, redacted Details, read-only Restore Plan surface, and guarded restore confirmation controls without preparing PDFs, writing reference files, recording drafts, or calling Gmail:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-iab-click-through --browser-answer-questions --browser-apply-history --json
```

The shell command returns a Node REPL handoff cell because raw subprocesses should not drive the in-app Browser directly.

To verify upload recovery and `Review Attention` without any browser driver or file-picker support, use the API-level source upload smoke:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --source-upload-checks --json
```

This uploads disposable synthetic photo/PDF sources directly to `/api/sources/upload`, checks Source Evidence, recovered PDF candidate fields, `Review Attention`, and `send_allowed: false`, and never calls `/api/prepare`, draft recording, draft status, or Gmail. It may store synthetic source-preview artifacts in the configured source upload folder; run it through `scripts/isolated_app_smoke.py --source-upload-checks --json` when you want that state fully disposable.

The browser app also exposes References -> Local Diagnostics. That panel lists the same safe smoke commands and lets you copy the default live smoke, source-upload smoke, isolated source-upload smoke, and Browser/IAB review smoke commands for PowerShell. The browser only copies commands; it does not run shell commands or call Gmail.

To include the local upload evidence and correction UI without creating PDFs or recording drafts, add the browser UI smoke flags:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-upload-photo --browser-upload-pdf --browser-correction-mode --json
```

These flags use disposable synthetic upload files, verify the `Source Evidence` card, check recovered PDF candidate fields, and exercise the draft lifecycle/correction reason surface. The upload endpoint can store synthetic source-preview artifacts locally, but the smoke still blocks prepare, record, and draft-status endpoints by default.

To verify the artifact-writing replacement path against disposable state that already has an active draft blocker, add `--browser-prepare-replacement`:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-correction-mode --browser-prepare-replacement --json
```

This clicks `Prepare replacement draft` with a synthetic correction reason and allows `/api/prepare`, so it may create local PDF and draft-payload artifacts. It still blocks `/api/drafts/record` and `/api/drafts/status`, never calls Gmail, and never records or sends a draft.

For the safest artifact-writing smoke, run the app against a fully isolated synthetic runtime instead of the real private workspace state:

```powershell
python scripts/isolated_app_smoke.py --interaction-checks --json
```

This starts a temporary local app whose `config/`, `data/`, `output/`, and `tmp/` paths all live in a disposable folder, then runs the draft-only smoke checks against that app. To exercise the replacement browser path against a seeded synthetic active draft, use:

```powershell
python scripts/isolated_app_smoke.py --browser-click-through --browser-correction-mode --browser-prepare-replacement --json
```

That command still never records drafts or calls Gmail. If Python Playwright is not installed, the browser part reports a clean tooling blocker; the isolated API smoke remains usable.

For a deeper opt-in workflow smoke against disposable/synthetic app state, add `--interaction-checks`:

```powershell
python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --interaction-checks --json
```

This exercises profile intake creation, active-draft checking, and packet-mode PDF/draft-payload preparation. It can write local PDF/payload artifacts on a real app, so keep it for test/synthetic state or intentional verification. It still checks that every response keeps `send_allowed: false` and never calls Gmail.

## Local Backups

Use References -> Local Backup before moving the app, making large reference edits, or preparing future LegalPDF integration work. `Export backup` writes a private JSON file under `output/backups/` and also shows the JSON in the app for copying. The backup includes service profiles, court emails, known destinations, duplicate index records, Gmail draft log records, and profile-change history.

The app now shows a `Latest backup` status card in References and warns when no recent backup exists before high-risk local edits such as saving profiles, court emails, destinations, profile rollbacks, or restoring backup data. A backup is considered fresh for 24 hours; the warning is advisory, but it is meant to catch exactly the kind of manual reference changes that would be painful to reconstruct.

Restores are preview-first. Paste backup JSON, click `Preview backup import`, review dataset counts, check the restore confirmation box, then click `Restore backup after preview`. The app writes an automatic pre-restore backup before replacing any local JSON file. These backup files contain private case/draft history and must not be published.

For future LegalPDF reintegration work, use References -> LegalPDF Integration Preview instead of the restore controls. It accepts a backup-like JSON and optional profile mappings such as `legalpdf_pj_beja = pj_gnr_beja`, then shows profile and court-email create/update/unchanged differences with `write_allowed: false`. You can also export a private Markdown/JSON preview report under `output/integration-reports/`, build a read-only integration checklist, or build a read-only adapter import plan that marks destructive profile updates and recipient drift as blockers.

The guarded apply button is available only for reviewed, non-blocked plans. It requires `confirm_apply=true`, the exact phrase `APPLY LEGALPDF IMPORT PLAN`, and an apply reason. It writes a pre-apply backup and private apply report, updates only this app's local reference files, never touches LegalPDF Translate, and never creates Gmail actions.

LegalPDF Apply History shows summary-only records of guarded applies, including private report/backup paths, applied profile/email counts, and preserved local defaults. Its Details button loads a read-only redacted hash/status comparison for touched profiles and court-email aliases. Its Restore plan button loads a hash-only preview of what a rollback would restore or remove from the pre-apply backup. The preview intentionally does not display the full import plan, source backup payload, or raw before/after reference values.

If a reviewed apply needs to be rolled back, the restore button requires `confirm_restore=true`, the exact phrase `RESTORE LEGALPDF APPLY BACKUP`, and a restore reason. The app writes a pre-restore backup first, restores or removes only the touched local profile/email records from the pre-apply backup, writes a private restore report, never touches LegalPDF Translate, and never creates Gmail actions.

OpenAI recovery is evidence-only. It may extract visible text, case/date/place clues, court email, and translation indicators from photos or scanned documents, but the existing duplicate checks, date-conflict questions, profile defaults, PDF generator, and Gmail draft safety rules remain authoritative. The OpenAI request uses a strict Responses JSON Schema named `honorarios_source_recovery`, so OCR/autofill returns predictable fields instead of free-form prose. The prompt also includes the learned honorários patterns for PJ/GNR host buildings, Beringel/Beja payment separation, Tribunal do Trabalho de Beja, Gabinete Médico-Legal de Beja, and word-count translation set-asides, while still telling the model not to infer kilometers, recipients, IBAN, or payment defaults. The app reports the AI schema name, prompt version, fields found, fields not found, and a `Review Attention` summary in Source Evidence so weak recovery, date conflicts, set-asides, duplicates, missing questions, source warnings, profile fallback, and profile proposals are visible before any PDF step. Uploaded sources now default to `Auto-detect profile`: local deterministic rules score the recovered evidence, choose a high-confidence profile such as `pj_gnr_beja`, `gnr_serpa_judicial`, or `beja_trabalho`, and show the decision in Source Evidence. If you manually choose a profile, that choice is kept and any conflicting automatic suggestion is shown only as review evidence. When no known profile matches but the evidence includes a stable service place/payment pattern, Source Evidence can show a `Profile proposal`; click `Preview proposed profile` to load it into the guarded profile editor, then preview/save it there. For Google Photos-style screenshots or selected-photo imports, compact filenames such as `20260415_205459.jpg` are treated as visible photo metadata and surfaced as `photo_metadata_date`; crop/partial-image warnings stay visible in Source Evidence. For weak/scanned notification PDFs, the app renders the first pages to local PNG evidence with `pdftoppm` when available and gives those images to OpenAI recovery. The app exposes `/api/ai/status` to show whether OpenAI OCR is ready without revealing the API key. Store optional local settings in ignored `config/ai.local.json`:

```json
{
  "openai_api_key": "sk-...",
  "model": "gpt-5.4-mini"
}
```

The Google Photos panel supports two safe source-import paths. The selected-photo bridge still works: choose or download one Google Photos image locally, paste the visible Google Photos metadata/filename/date into the metadata box, and recover through the same photo pipeline. When private local OAuth credentials are configured, the app can also start a Google Photos Picker session, let you choose one image in Google Photos, download only that selected image into local source evidence, and run the normal review flow. `/api/google-photos/status` reports readiness without showing any client secret, access token, refresh token, raw photo URL, media base URL, or selected media ID.

Store optional Google Photos OAuth settings in ignored `config/google-photos.local.json` or environment variables. Use `config/google-photos.example.json` as the public-safe template:

```json
{
  "client_id": "example-client-id.apps.googleusercontent.com",
  "client_secret": "example-client-secret",
  "redirect_uri": "http://127.0.0.1:8766/api/google-photos/oauth/callback",
  "token_path": "config/google-photos-token.local.json"
}
```

Equivalent environment variables are `GOOGLE_PHOTOS_CLIENT_ID`, `GOOGLE_PHOTOS_CLIENT_SECRET`, `GOOGLE_PHOTOS_REDIRECT_URI`, and `GOOGLE_PHOTOS_TOKEN_PATH`. Tokens are stored only in ignored local files. Google Photos import is source-only: it never creates a Gmail draft by itself and never sends email.

### CLI Workflow

1. For a familiar service pattern, create the intake from a reusable profile:

   ```powershell
   python scripts/create_intake.py --profile pj_gnr_ferreira --case-number 86/26.8GAFAL --service-date 2026-02-15
   ```

   Current profiles live in `data/service-profiles.json`: `pj_gnr_ferreira`, `pj_medico_legal_beja`, `pj_gnr_beja`, `beja_trabalho`, `gnr_beringel_beja_mp`, `gnr_ferreira_falentejo`, `gnr_serpa_judicial`, `gnr_cuba`, and `court_mp_generic`.

   For a new or unusual pattern, put the details from the photo/document into an intake JSON file manually. Start from:

   `examples/intake.example.json`

2. Prepare the PDF and Gmail draft payload in one checked batch:

   ```powershell
   python scripts/prepare_honorarios.py examples/intake.example.json --allow-duplicate --render-previews
   ```

3. Review the printed summary before creating any Gmail draft. It shows the case number, effective service date, payment entity, physical service entity, recipient email, PDF path, draft payload path, and `gmail_create_draft_args`.

4. The PDF is written to `output/pdf/`, the local draft payload to `output/email-drafts/`, and a review manifest to `output/manifests/`.

The older single-purpose commands still exist for debugging:

```powershell
python scripts/check_duplicate.py examples/intake.example.json
python scripts/generate_pdf.py examples/intake.example.json --allow-duplicate
python scripts/build_email_draft.py examples/intake.example.json --pdf output/pdf/398-24.5T8BJA_2026-02-05.pdf
```

`service_date_source` should be one of: `document_text`, `photo_metadata`, `document_text_and_photo_metadata`, `user_confirmed`, `user_confirmed_exception`, `document_text_user_confirmed`, or `photo_metadata_user_confirmed`.

Profile selection shortcuts:

- `pj_gnr_ferreira`: Polícia Judiciária using the Posto da GNR de Ferreira do Alentejo, paid by the Ferreira court.
- `pj_gnr_beja`: Polícia Judiciária using the Posto da GNR de Beja, paid by Ministério Público de Beja.
- `pj_medico_legal_beja`: Polícia Judiciária victim accompaniment to Gabinete Médico-Legal de Beja / Hospital José Joaquim Fernandes - Beja.
- `beja_trabalho`: Tribunal do Trabalho de Beja / Juízo do Trabalho de Beja only.
- `gnr_beringel_beja_mp`: GNR service in Beringel, paid by Ministério Público de Beja.
- `gnr_ferreira_falentejo`: GNR service at the Posto da GNR de Ferreira do Alentejo without PJ context.
- `gnr_serpa_judicial`: GNR service at the Posto Territorial de Serpa, paid by the Serpa court.
- `gnr_cuba`: GNR Cuba, with payment entity supplied by the source/user.
- `court_mp_generic`: fallback for court/MP services where payment and service entity are the same.

## What This Project Needs From A New Photo

The minimum information needed for an interpreting honorarios PDF is:

- Process number (`Numero de processo`)
- Service date, meaning the date the interpreting service happened
- Time period, when the same case has more than one service on the same date
- Photo metadata date, when the visible image details show the service/capture date and the paper itself does not clearly state the service date
- Institution/place attended in person, such as a tribunal, GNR post, PSP station, or court service
- Addressee/court or Ministerio Publico destination
- Payment entity, meaning the court/Ministério Público/entity from which payment is requested
- Service entity, meaning where the interpreting service actually happened
- Whether transport expenses should be claimed
- If transport is claimed: origin, destination, and one-way kilometers

If a photo contains only a document date or signature date, that is not enough for the service date.

If the phone/gallery metadata shown beside the image gives the relevant service/capture date, use that as `photo_metadata_date` and treat it as the priority signal. Printed timestamps inside the legal paper, such as appointment or document timestamps, should not override the photo metadata unless you confirm the exception. If there is a conflict, ask a numbered question before generating anything.

If the photo header shows a court or Ministério Público office and there is no separate GNR/PSP/police clue, the header usually counts as both payment entity and service place. If the service was done at GNR, PSP, police, or another non-court entity, the payment entity and service entity differ, so the PDF body must explicitly say where the service happened.

For Polícia Judiciária sources, record the local host building and city used for the service. PJ often travels from elsewhere and uses a GNR building, hospital, or medical-legal office, so `Polícia Judiciária` alone is not enough as the service place. Use a physical place such as `Posto da GNR de Ferreira do Alentejo` or `Gabinete Médico-Legal de Beja, Hospital José Joaquim Fernandes - Beja`. Inspector names are optional; include them if visible and useful, but do not ask for them when missing.

For similar photo batches, either use the browser app's Batch Queue or prepare all intake files together from the CLI. In the browser, click `Check batch preflight` first: it validates the queued requests, same-batch duplicates, active draft blockers, and packet recipient compatibility without writing PDFs, draft payloads, intake JSON, or manifests. `Prepare batch package` stays disabled until that clean preflight matches the current queue and packet-mode setting. Adding, removing, reordering, clearing, or toggling packet mode stales the previous preflight, so run the non-writing check again before generating artifacts.

When a batch should be sent as a single attachment, turn on `Packet mode` in the browser before clicking `Prepare batch package`. Use the packet order controls to drag queued requests or move them up/down first. Use each row's `Inspect` button to open the Packet item inspector and confirm the request's recipient, service place, kilometers, source details, and supporting attachment order. The app validates that all queued requests use the same recipient, creates the individual requerimento PDFs in the displayed order, bundles them into one packet PDF, and prepares one Gmail `_create_draft` payload with the packet as the only attachment. After the packet is prepared, use the Packet draft recording helper to copy the `record_gmail_draft.py` command or JSON object; it includes the packet payload path and the underlying requests that will become duplicate blockers once the draft is recorded. In the Review drawer, the Record Gmail Draft card also has `Autofill from prepared payload`; paste the Gmail draft/message/thread IDs first, then use that button to fill the prepared packet or individual payload path without clearing the pasted IDs.

```powershell
python scripts/prepare_honorarios.py examples/intake.gnr-cuba-photo-metadata-146.example.json examples/intake.gnr-cuba-photo-metadata-15.example.json --render-previews
```

When information is missing, questions must be numbered so you can answer compactly:

```text
1. What was the service date? (Use YYYY-MM-DD.)
2. What was the destination? (A city name is enough.)
```

You can reply with short numbered answers:

```text
1. 2026-05-02
2. Beja
```

In the browser app, paste the same compact format into the `Numbered answers` card in the review drawer, then click `Apply numbered answers`. The app updates the current intake, reruns duplicate/date/profile review, and still keeps PDF generation and Gmail draft preparation behind the normal review steps.

## Translation Requests Are Set Aside

Do not use this project for requests that mention:

- `tradutor`
- `traducao`
- `documento traduzido`
- `numero de palavras`
- word counts such as `contém 1500 palavras`

Those are translation honorarios, not in-person interpreting honorarios.

## Duplicate Check

Before creating a new PDF, check whether the same case number and service date already exist:

```powershell
python scripts/check_duplicate.py examples/intake.example.json
```

The duplicate list lives in:

`data/duplicate-index.json`

This file is the single duplicate-warning source for both sent and drafted honorários. Records with `status: sent` or `status: drafted` block future generation. Older records without a `status` are treated as already sent. Superseded, trashed, and not-found draft records remain auditable but do not block.

If a match is found, stop and treat the new paper as most likely a duplicate until the user confirms otherwise. For repeated same-day work, the check also uses `service_period_label`: exact same case/date/period blocks, while different periods such as morning and afternoon can coexist.

The PDF generator also checks this by default. Use `--allow-duplicate` only when intentionally regenerating an existing example or when the user has confirmed the match is not a problem.

## Gmail Drafts Only

After a PDF is ready, the project prepares a Gmail draft payload. It does not send email.

- If the source document/image contains a court email address, use that recipient.
- If no court email is present, use `court@example.test` only when it is consistent with the payment entity; otherwise use the matching known profile/key or ask before drafting.
- The draft recipient is the payment entity/court email, not necessarily the place where the service physically happened.
- Draft payloads include case number, service date, payment entity, service entity, attachment filename, and a PDF hash.
- Draft payloads also include `gmail_create_draft_args`, which can be passed directly to Gmail `_create_draft`. Its `attachment_files` value is always an array, even for a single PDF.
- Subject is always `Requerimento de honorários`.
- Body is stored in `config/email.json`.
- If supporting proof such as a `declaração` should be attached, add it to `additional_attachment_files` in the intake. If the email must mention it, set `email_body` for that intake. Pass `attachment_files` to `_create_draft` as an array of absolute local file paths.
- When the user wants several source files bundled together, create a combined packet PDF and attach that PDF.
- Future assistant sessions must use Gmail `_create_draft` only and must not use send tools unless you explicitly ask after review.

After `_create_draft` returns, record the Gmail draft IDs in:

`data/gmail-draft-log.json`

Recording a draft also writes a `status: drafted` duplicate record to `data/duplicate-index.json` immediately, so future requests warn before you accidentally ask for the same case/date again. Do not wait for the email to be sent before adding duplicate protection.

Use the short payload-based form whenever possible:

```powershell
python scripts/record_gmail_draft.py --payload <payload-json> --draft-id <draft-id> --message-id <message-id> --thread-id <thread-id>
```

In the browser app, the Record Gmail Draft card can parse a pasted Gmail `_create_draft` response and fill the draft/message/thread ID fields locally. It can also fill the payload path and active status from the latest prepared packet or individual payload while preserving already pasted IDs. The lowest-friction path is: create the draft with `_create_draft`, paste the returned connector response, then click `Record parsed response + prepared payload`. That parses the IDs, fills the latest packet or individual payload path, and records the draft locally without creating, sending, or modifying any Gmail message.

The older explicit form still works:

```powershell
python scripts/record_gmail_draft.py --case-number <case> --service-date <YYYY-MM-DD> --recipient <email> --pdf <pdf> --draft-payload <payload-json> --draft-id <draft-id> --message-id <message-id> --thread-id <thread-id>
```

If a draft needs correction, create a new corrected draft first, then mark the old record as superseded/trashed in the log and only then move the old Gmail message to Trash. Use `--allow-existing-draft` with `scripts/prepare_honorarios.py` only when you are intentionally correcting/replacing a logged active draft, and always include `--correction-reason "<short reason>"` so the manifest keeps an audit trail. Never send either draft automatically.

When a draft is manually sent later, update the matching duplicate-index record from `status: drafted` to `status: sent` and add `sent_date`:

```powershell
python scripts/record_gmail_draft.py --payload <payload-json> --draft-id <draft-id> --message-id <message-id> --status sent --sent-date <YYYY-MM-DD>
```

For packet emails containing multiple honorários requests, store one duplicate-index record per underlying request, not just one record for the packet attachment.

## Stored Defaults

Reusable personal and payment details live in:

`config/profile.json`

Keep that file local. It contains payment details that should not be shared publicly.

For future public GitHub publishing, keep real runtime files local and ignored: `config/profile.json`, `data/gmail-draft-log.json`, `data/duplicate-index.json`, `data/profile-change-log.json`, `data/precedents.json`, `output/`, and `tmp/`. Publish only sanitized seed examples and synthetic tests.

Public sanitized repository:

<https://github.com/Adel199223/honorarios-interpreting>

That repository was created from a sanitized candidate, not from this private working folder.

Run the executable privacy/readiness gate before creating a public repository:

```powershell
python scripts/public_release_gate.py --json
```

The same check is available in the browser app under References -> Public GitHub Readiness. A blocked result is expected in this working folder because it contains real local profile/payment data, generated artifacts, draft logs, and case history. Publish only from a separate sanitized candidate after the gate passes.

To build that separate sanitized candidate, use:

```powershell
python scripts/build_public_candidate.py --target output/public-candidate --json
```

The browser app exposes the same step under References -> Public GitHub Readiness -> Build sanitized candidate. The generated candidate uses synthetic profile, email, court, destination, service-profile, and intake examples, then runs the same privacy gate against the candidate tree. Review that candidate before initializing or pushing a public GitHub repository.

## Improving The Project

Each time a new document reveals a better wording pattern, update:

- `docs/template-patterns.md`
- `docs/question-rules.md`
- `data/known-destinations.json`
- `data/precedents.json`
- `data/duplicate-index.json`
- `data/court-emails.json`

Then add or update a sample intake file and run the tests.

For simple kilometer/destination updates, recurring court email aliases, or guarded service-profile defaults, you can also use the browser app's References screen. It validates `km_one_way`, email format, aliases, service date sources, service entity types, and recipient consistency; it writes only the reference JSON/change log and does not create or send Gmail messages.

## Verification

Run:

```powershell
python scripts/generate_pdf.py examples/intake.example.json --allow-duplicate
python scripts/build_email_draft.py examples/intake.example.json --pdf output/pdf/398-24.5T8BJA_2026-02-05.pdf
python scripts/prepare_honorarios.py examples/intake.gnr-cuba-photo-metadata-15.example.json
python -m unittest discover tests
```

For visual checks, render the generated PDF:

```powershell
pdftoppm -png output/pdf/398-24.5T8BJA_2026-02-05.pdf tmp/pdfs/rendered
```
