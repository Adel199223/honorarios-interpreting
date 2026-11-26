---
name: honorarios-request-workflow
description: >-
  End-to-end Antigravity runbook for reviewing an interpreting source, checking
  duplicates and exclusions, generating Portuguese honorários PDFs, creating
  an unsent Gmail draft safely, and recording returned draft IDs locally.
---

# Honorários Request Workflow (Antigravity)

Use this skill whenever preparing an in-person interpreting `requerimento de honorários` PDF and unsent Gmail draft from a photo, PDF notice, or intake JSON.

## 1. Classify and Inspect Source

1. Confirm the source is an in-person interpreting service.
   - AI OCR/extraction defaults to Gemini 4 Neon (`thinking_level="xhigh"`) plus calibrated Decisions API (`gemini-decision-1`) screening when `GEMINI_API_KEY` or `config/ai.local.json` is set (OpenAI remains supported as fallback); both remain evidence only behind deterministic rules.
   - Set aside written-translation-only or word-count notices.
   - If a mixed notice has an explicit in-person interpreting appointment, bill only interpreting. If ambiguous, ask a numbered scope question.
   - Skip police-prepared fee-request forms (signed or unsigned) and PSP PAC procedures per local policy.
2. For sideways, cropped, or low-contrast photos, create temporary rotated/cropped inspection copies outside the workspace before asking the user to read a `case_number`.
3. Check `data/duplicate-index.json`, `data/gmail-draft-log.json`, and any local exclusions before generating anything. If any required field is missing or dates conflict, ask numbered questions matching `docs/question-rules.md`.

### Complete Period Audit Checklist

- **Scan every image regardless of file size**: When auditing a Camera folder period, inspect all image files including high-megapixel originals (`>10 MB` and `>25 MiB` files hidden by the Camera UI picker) plus sibling folders (`DCIM/Document scans`, `DCIM/Screenshots`). Visually inspect every document-like candidate before skipping it.
- **Check both dates on summons (`Nota de Notificação`) photos**: In Portuguese summary proceedings (*processo sumário — fase preliminar*), a summons for a future hearing is often handed over on a day when the interpreter also worked on that same case. Never assume a summons photo represents only the future appointment date — check `data/duplicate-index.json`, `data/gmail-draft-log.json`, and Gmail Sent attachments for **both** the capture/issue date and the future appointment date. If the capture/issue date is unbilled, confirm with the user whether interpreting work also occurred on that date rather than dropping it.
- **Verify Gmail Sent and Drafts by PDF attachment filenames**: Generic subjects (`Requerimento de honorários` / plural `Requerimentos de honorários`) omit case numbers, so Gmail keyword searches for case numbers will miss sent emails. Always inspect actual message/draft attachment filenames (including grouped multi-PDF emails) and verify every `(filename, case_number, service_date, gmail_id)` mapping directly before reporting.

## 2. Create Intake and Prepare PDF + Previews

Use the pinned `.venv311` interpreter for all commands:

```powershell
# Optional: scaffold from a service profile
.\.venv311\Scripts\python.exe scripts/create_intake.py --profile example_interpreting --case-number 999/26.0SMOKE --service-date 2026-05-04

# Batch preflight, PDF generation, draft payload build, and preview PNG rendering
.\.venv311\Scripts\python.exe scripts/prepare_honorarios.py <intake-json> --render-previews
```

Visually inspect every rendered preview PNG in `output/previews/` with `read_file` before proceeding to Gmail. Verify case number, effective service date, payment entity, service entity/location, travel distance, IBAN/tax wording, and recipient email.

## 3. Create Unsent Gmail Draft (Draft-Only)

Never send emails, trash messages, or delete drafts automatically (`_send_email` / `_send_draft` / `gmail mutate send` are forbidden).

### Option A: In-App Gmail Draft API (when OAuth is connected)
Use the browser app's guarded `Create Gmail Draft` button (`users.drafts.create` after PDF preview and checklist confirmation).

### Option B: Antigravity Gmail CLI (`Manual Draft Handoff`)
Prepare a validated Windows PowerShell command and UTF-8 body file with:

```powershell
.\.venv311\Scripts\python.exe scripts/antigravity_gmail_handoff.py --payload <prepared-draft.json>
```

That helper validates `draft_only: true`, `send_allowed: false`, `gmail_create_draft_ready: true`, and SHA-256 attachment hashes, writes the email body as UTF-8 `--body-file`, and prints the exact `$env:AGY_UNATTENDED = "1"; gmail mutate create-draft ...` command with repeatable `--file` flags.

Run the printed `gmail mutate create-draft` command, and if needed inspect the created draft read-only:

```powershell
gmail readonly get-draft <DRAFT_ID>
```

## 4. Record Returned Draft IDs Locally

Immediately after draft creation, record the returned IDs so duplicate protection activates:

```powershell
.\.venv311\Scripts\python.exe scripts/record_gmail_draft.py --payload <prepared-draft.json> --draft-id <DRAFT_ID> --message-id <MESSAGE_ID> --thread-id <THREAD_ID>
```

Leave the draft in Gmail for the user to review and send manually.
