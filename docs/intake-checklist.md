# Intake Checklist

Use this checklist whenever a new photo or document is provided.

## First Classification

Classify the source before generating anything.

Include it only if the substance is in-person interpreting:

- The person was appointed as `intérprete`.
- The source refers to attendance or service on a specific day.
- The source mentions a court, Ministério Público, GNR, PSP, police, or another in-person service location.
- The source may include transport expenses, kilometers, or travel between Marmelar and another city.

Set it aside if it looks like translation:

- It says `tradutor`.
- It says `tradução`.
- It mentions `documento traduzido`.
- It mentions `número de palavras`, `palavras`, or another word-count phrase.

## Required Fields

For recurring service patterns, create the first draft of the intake from `data/service-profiles.json`:

```powershell
python scripts/create_intake.py --profile pj_gnr_ferreira --case-number 86/26.8GAFAL --service-date 2026-02-15
```

Then add only the details that are specific to the new source, such as a time period, declaration attachment, or exceptional recipient.

Before generating a PDF, confirm these fields:

- `case_number`: exact process number.
- `service_date`: explicit service date in `YYYY-MM-DD`.
- `photo_metadata_date`: image capture/service date in `YYYY-MM-DD` when the paper does not clearly state the service date.
- `service_date_source`: one of `document_text`, `photo_metadata`, `document_text_and_photo_metadata`, `user_confirmed`, `user_confirmed_exception`, `document_text_user_confirmed`, or `photo_metadata_user_confirmed`.
- `service_period_label`: optional label such as `morning` or `afternoon` when the same case has multiple services on the same date.
- `service_start_time` and `service_end_time`: optional pair used when the declaration gives a specific time period.
- `addressee`: full court/prosecutor/addressee block.
- `payment_entity`: court, Ministério Público, or other entity asked to pay.
- `service_entity`: place/entity where the interpreting service happened.
- `service_entity_type`: `court`, `ministerio_publico`, `gnr`, `psp`, `police`, or `other`.
- `entities_differ`: `true` when payment and service entities are different.
- `service_place`: institution/place attended in person.
- `service_place_phrase`: optional exact phrase such as `no posto territorial da GNR de Cuba` or `na esquadra da PSP de Moura`.
- `closing_city`: usually `Beja`, unless another city is appropriate.
- `closing_date`: document date in `YYYY-MM-DD`.

If any required field is missing, ask numbered questions in stable order. Short numbered answers are acceptable, such as:

```text
1. 2026-05-02
2. Beja
3. 39
```

Command:

```powershell
python scripts/intake_questions.py <intake-json>
```

## Duplicate Check

Before generating a PDF, compare `case_number` and the effective service date against:

```text
data/duplicate-index.json
```

If both fields match an existing record with `status: sent` or `status: drafted`, stop before generating the PDF and tell the user it is most likely a duplicate. Old records without `status` are treated as sent. The effective service date is `service_date` when present, otherwise `photo_metadata_date`. Case numbers are normalized for leading zeros, and period labels are normalized for repeated same-day work.

Command:

```powershell
python scripts/check_duplicate.py <intake-json>
```

For complete intakes, prefer the all-in-one preflight command:

```powershell
python scripts/prepare_honorarios.py <intake-json> [<intake-json> ...] --render-previews
```

It checks missing information, date conflicts, duplicates, PDF text content, draft payload safety, recipient/payment consistency, and writes a manifest before Gmail draft creation.

## Payment Entity vs Service Entity

When reading the source:

- If the header is a court or Ministério Público and there is no separate GNR/PSP/police clue, infer that `payment_entity` and `service_entity` are the same.
- If the source mentions GNR, PSP, police, `posto`, `esquadra`, `destacamento`, `hospital`, `gabinete`, or another non-court service location, record that as `service_entity`.
- If payment and service entities differ, set `entities_differ` to `true` and ensure the generated body explicitly mentions the service place.
- For Polícia Judiciária sources, also record the local host building and city, such as `Posto da GNR de Ferreira do Alentejo` or `Gabinete Médico-Legal de Beja, Hospital José Joaquim Fernandes - Beja`. PJ commonly uses another building away from its own office, so `Polícia Judiciária` or `Diretoria` alone is not enough.
- Inspector names are optional. Include an inspector only when visible and useful; do not ask the user for one when missing.

Canonical examples:

- Court same: `payment_entity = Tribunal de Beja`, `service_entity = Tribunal de Beja`.
- GNR different: `payment_entity = Tribunal Judicial de Cuba`, `service_entity = Posto Territorial da GNR de Cuba`.
- GNR Serpa different: `payment_entity = Tribunal Judicial de Serpa`, `service_entity = Guarda Nacional Republicana / Posto Territorial de Serpa`, `transport.km_one_way = 34`.
- PSP different: `payment_entity = Tribunal de Moita`, `service_entity = Esquadra da PSP de Moura`.
- PJ/GNR different: `payment_entity = Tribunal Judicial de Ferreira do Alentejo`, `service_entity = Polícia Judiciária - Diretoria do Sul / Posto da GNR de Ferreira do Alentejo`, `service_place = Posto da GNR de Ferreira do Alentejo`.
- PJ/medical-legal different: `payment_entity = Tribunal Judicial de Ferreira do Alentejo`, `service_entity = Polícia Judiciária - Diretoria do Sul / Gabinete Médico-Legal de Beja`, `service_place = Gabinete Médico-Legal de Beja, Hospital José Joaquim Fernandes - Beja`.

## Image Metadata Date

For photographed documents:

- Use `service_date` when the paper explicitly says the date the interpreting service happened.
- Use `photo_metadata_date` as the priority signal when the visible image metadata gives the relevant date.
- Do not use printed appointment timestamps, procedural timestamps, closing dates, or document creation dates as the service date unless the user confirms.
- If `service_date` and `photo_metadata_date` conflict and both seem plausible service dates, ask a numbered clarification question.
- When the user confirms an exception, set `service_date_source` to `user_confirmed_exception`.
- Put the reason in `notes`, for example: `User confirmed this exceptional case uses the printed 2026-02-12 timestamp instead of the 2026-02-16 photo metadata date.`

## Transport Fields

If transport is claimed, confirm:

- `claim_transport`: `true`.
- `transport.origin`: usually `Marmelar`.
- `transport.destination`: city/place traveled to.
- `transport.km_one_way`: one-way kilometers.

If transport is not claimed, set:

```json
"claim_transport": false
```

## Optional Fields

Use these when the source gives more context:

- `recipient_email`
- `court_email`
- `court_email_key`
- `payment_entity`
- `service_entity`
- `service_entity_type`
- `entities_differ`
- `source_text`
- `photo_metadata_date`
- `service_date_source`
- `source_document_timestamp`
- `source_filename`
- `notes`
- `round_trip_phrase`: `ida_volta` or `cada_sentido`

## Email Draft

After the PDF is generated and visually checked, create a draft payload:

```powershell
python scripts/build_email_draft.py <intake-json> --pdf <generated-pdf>
```

Recipient rules:

- Use a court email found in the source text/image if one is present.
- Otherwise use `court_email`, `recipient_email`, or a valid `court_email_key` from the intake if present. Unknown `court_email_key` values must fail instead of falling back.
- Otherwise use `court@example.test`.
- The recipient should be the payment entity/court address, not necessarily the physical service entity.

Create a Gmail draft only. Do not send. Draft payloads must validate before Gmail: `attachment_files` must be an array of absolute existing files, `gmail_create_draft_args` must be present, `draft_only` must be true, `send_allowed` must be false, and `gmail_create_draft_ready` must be true.

After draft creation, record the returned draft ID/message ID/thread ID in `data/gmail-draft-log.json` using `scripts/record_gmail_draft.py`.

## Do Not Guess These

Ask the user instead of guessing:

- Service date.
- Process number.
- Whether to claim transport expenses.
- Kilometers when no known destination matches.
- Addressee when the photo does not identify the tribunal or Ministerio Publico.
- Recipient/payment mismatch when the payment entity maps to a known court email but the intake points somewhere else. Ask or require `recipient_override_reason`.
- Polícia Judiciária host building/city when the source shows PJ but does not identify the local place used for the service.
