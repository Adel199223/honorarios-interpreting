# LegalPDF Adapter Contract

This contract describes how a future LegalPDF Translate integration should call the standalone LegalPDF Honorários workflow without copying its internals or bypassing its safety rules.

Current contract version: `2026-05-07.manual-handoff.v1`

## Boundary

LegalPDF Translate remains read-only from this app. The Honorários app owns:

- PDF generation and PDF previews.
- Personal profile adaptation for applicant, payment, address, IVA/IRS, IBAN, and travel origin.
- Service profile detection and service/payment entity rules.
- Duplicate and active-draft protection.
- Draft-only Gmail payload validation.
- Manual Draft Handoff and local draft recording.

The future LegalPDF adapter may call the Honorários app endpoints, but it must not write directly to LegalPDF Translate or mutate Honorários JSON files outside the app APIs.

## Allowed Sequence

1. Recover a source or start with a blank request.
   - Endpoint: `POST /api/sources/upload`
   - Effect: stores local source evidence inside this app only.

2. Review the intake.
   - Endpoint: `POST /api/review`
   - Effect: read-only review result with draft text, source evidence, duplicate/active-draft warnings, translation set-asides, and numbered questions.

3. Apply numbered answers if needed.
   - Endpoint: `POST /api/review/apply-answers`
   - Effect: updates the request context and reruns review. It must not skip duplicate, date-conflict, recipient, or draft-only checks.

4. Run non-writing batch preflight.
   - Endpoint: `POST /api/prepare/preflight`
   - Effect: validates queued requests without writing PDFs, payloads, manifests, draft logs, duplicate records, or reference data.

5. Prepare artifacts after review/preflight is ready.
   - Endpoint: `POST /api/prepare`
   - Effect: writes this app's generated PDFs, previews, manifests, and draft payloads only.

6. Build the Manual Draft Handoff packet.
   - Endpoint: `POST /api/gmail/manual-handoff`
   - Effect: read-only. Reloads the prepared payload, validates attachment paths, and returns copy-ready draft-only handoff text with attachment names and hashes.

7. Record the created draft.
   - Endpoint: `POST /api/drafts/record`
   - Effect: writes this app's draft log and duplicate index only, after the Gmail draft exists and the handoff checklist has been reviewed.

## Required Safety Rules

- Missing information must be shown as numbered questions.
- Translation or word-count sources must be set aside before generation.
- Metadata/document date conflicts must block generation until the user confirms the correct date.
- `drafted` and `sent` duplicate records must block generation.
- Active drafts must block normal generation unless correction mode has a short reason.
- Packet drafts must keep `underlying_requests` so every case/date/period receives duplicate protection.
- Prepared PDFs, previews, draft payloads, manual handoff packets, and record-helper values are stale after source, review, profile, queue, packet-mode, or intake changes.
- Gmail OAuth is optional. Manual Draft Handoff is the always-available Gmail boundary for this contract.

## Forbidden Capabilities

The adapter must not add Gmail sending, draft sending, mailbox search, trash/delete behavior, direct duplicate-index bypasses, or direct LegalPDF Translate writes.

## Read-Only Contract Endpoint

The app exposes:

```text
GET /api/integration/adapter-contract
```

The response is secret-free and includes:

- `contract_version`
- allowed endpoint sequence
- Gmail boundary
- caller responsibilities
- safety flags
- `send_allowed: false`
- `write_allowed: false`
- `legalpdf_write_allowed: false`
- `managed_data_changed: false`

Use that endpoint as the machine-readable source for future LegalPDF integration planning.
