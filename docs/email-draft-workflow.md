# Gmail Draft Workflow

Every completed interpreting honorários PDF should lead to a Gmail draft, not a sent email.

## Recipient Rule

1. If the source document/image contains a court email address, use that email.
2. If the intake explicitly includes `court_email` or `recipient_email`, use that email.
3. If there is no court email and the payment entity does not map to a more specific known address, use the default Ministério Público de Beja address:

```text
court@example.test
```

Known recurring addresses are listed in `data/court-emails.json`.
Unknown `court_email_key` values must fail instead of falling back. Generic `Tribunal de Beja` maps to the normal Beja Ministério Público address; the labor-court address is reserved for explicit `Tribunal do Trabalho de Beja` / `Juízo do Trabalho de Beja` cases.

The recipient is the payment entity/court/Ministério Público address. It may be different from the service entity when the interpreting happened at GNR, PSP, police, or another non-court location.

## Draft Content

Subject:

```text
Requerimento de honorários
```

Body:

```text
Bom dia,

Venho por este meio, requerer o pagamento dos honorários devidos, em virtude de ter sido nomeado intérprete.

Poderão encontrar o requerimento de honorários em anexo.

Melhores cumprimentos,

Example Interpreter
```

## Safety Rule

Use only the Gmail draft tool:

```text
_create_draft
```

Do not use `_send_email` or `_send_draft` unless the user explicitly asks to send after reviewing the draft.

## Batch Command

Prefer preparing the PDF and draft payload together:

```powershell
python scripts/prepare_honorarios.py <intake-json> [<intake-json> ...] --render-previews
```

The command writes:

- PDF files to `output/pdf/`.
- Draft payloads to `output/email-drafts/`.
- A batch review manifest to `output/manifests/`.

Review the manifest summary before using Gmail. It should make the case number, service date, payment entity, service entity, recipient, and attachment path visible in one place.

By default, the command blocks if `data/gmail-draft-log.json` already has an active Gmail draft for the same case number and service date. Use `--allow-existing-draft` only when intentionally preparing a corrected replacement.

## Single Payload Command

Build a local draft payload after the PDF exists:

```powershell
python scripts/build_email_draft.py examples/intake.example.json --pdf output/pdf/398-24.5T8BJA_2026-02-05.pdf
```

The payload tells the future assistant which recipient, subject, body, and PDF attachment to pass to `_create_draft`. Before Gmail, validate that `attachment_files` is an array of absolute existing files, `gmail_create_draft_args` is present, `draft_only` is true, `send_allowed` is false, and `gmail_create_draft_ready` is true.

Draft payloads also include case number, service date, payment entity, service entity, attachment basename, payload schema version, and PDF SHA-256 hash. If `recipient_email`, `court_email`, or `court_email_key` is present but invalid, draft payload creation must stop instead of falling back. If multiple `@tribunais.org.pt` emails are visible in the source, ask which one is the payment recipient instead of choosing the first.

Draft payloads include a connector-ready object:

```json
"gmail_create_draft_args": {
  "to": "court@example.test",
  "subject": "Requerimento de honorários",
  "body": "...",
  "attachment_files": ["C:\\...\\output\\pdf\\86-26.8GAFAL_2026-02-15.pdf"]
}
```

Pass that object to Gmail `_create_draft`. The `attachment_files` value is always an array, even for one PDF.

When the user asks to include supporting proof, such as a `declaração`, add the file path to `additional_attachment_files` in the intake. The generated honorários PDF remains the primary attachment, and the draft payload must include all files in `attachment_file_list`. Use `email_body` in the intake only when that specific draft needs wording different from the default body, for example to mention that both the honorários request and declaration are attached. Pass `attachment_files` to Gmail `_create_draft` as an array of absolute local file paths.

If the user wants several source files packaged together, build a combined packet PDF with `scripts/build_packet_pdf.py`. Use the packet PDF as the only `attachment_files` item and mention every included requerimento/declaração in `email_body`.

## Draft Log

After `_create_draft` returns, record the returned IDs:

```powershell
python scripts/record_gmail_draft.py --payload <payload-json> --draft-id <draft-id> --message-id <message-id> --thread-id <thread-id>
```

The log lives at:

```text
data/gmail-draft-log.json
```

Use it to avoid losing track of active, superseded, trashed, or not-found drafts.

The same command also upserts a `status: drafted` duplicate record in:

```text
data/duplicate-index.json
```

This happens immediately after draft creation, before manual sending, so future duplicate checks can warn about case/date pairs that already have a draft. When the draft is manually sent later, update the same duplicate-index record to `status: sent` and add `sent_date`:

```powershell
python scripts/record_gmail_draft.py --payload <payload-json> --draft-id <draft-id> --message-id <message-id> --status sent --sent-date <YYYY-MM-DD>
```

The older explicit recording form still works for manual recovery:

```powershell
python scripts/record_gmail_draft.py --case-number <case> --service-date <YYYY-MM-DD> --recipient <email> --pdf <pdf> --draft-payload <payload-json> --draft-id <draft-id> --message-id <message-id> --thread-id <thread-id>
```

For repeated same-day services, draft log records may include `service_period_label`, `service_start_time`, and `service_end_time`. Exact same case/date/period active drafts block a new preflight; different periods such as morning and afternoon can coexist.

For packet emails containing multiple honorários requests, write one duplicate-index record for each underlying request. For example, a packet with morning and afternoon requerimentos on the same case/date needs separate `morning` and `afternoon` duplicate records even though Gmail has one draft and one attachment.

## Correction Workflow

If a draft has the wrong recipient, attachment, or case mapping:

1. Do not send or edit the mistaken draft.
2. Correct the intake and run `scripts/prepare_honorarios.py --allow-existing-draft` again.
3. Create a new Gmail draft with `_create_draft`.
4. Record the new draft in `data/gmail-draft-log.json`.
5. Ensure the corrected draft remains `status: drafted` in `data/duplicate-index.json`.
6. Mark the old draft as `superseded` or `trashed`, including the new `superseded_by` draft ID.
7. Trash only the old Gmail message ID after verifying its recipient, subject, and attachment belong to the mistaken draft.
