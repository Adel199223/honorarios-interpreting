# LegalPDF Adapter Contract

This contract describes how a future LegalPDF Translate integration should call the standalone LegalPDF Honorários workflow without copying its internals or bypassing its safety rules.

Current contract version: `2026-05-09.prepared-review.v2`

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
   - Response: keep the returned `preflight_review` with `review_fingerprint` and `preflight_review_token`.

5. Prepare artifacts after review/preflight is ready.
   - Endpoint: `POST /api/prepare`
   - Effect: writes this app's generated PDFs, previews, manifests, and draft payloads only.
   - Request: pass the current `preflight_review` for the same queue snapshot.
   - Response: keep the returned `prepared_review` with `manifest`, `prepared_review_token`, `review_fingerprint`, and `payload_paths`.

6. Build the Manual Draft Handoff packet.
   - Endpoint: `POST /api/gmail/manual-handoff`
   - Effect: read-only. Reloads the prepared payload, validates attachment paths, and returns copy-ready draft-only handoff text with attachment names and hashes.
   - Request: pass `payload`, `prepared_manifest`, `prepared_review_token`, and `review_fingerprint` from the current `/api/prepare` response.

7. Record the created draft.
   - Endpoint: `POST /api/drafts/record`
   - Effect: writes this app's draft log and duplicate index only, after the Gmail draft exists and the handoff checklist has been reviewed.
   - Request: pass the same prepared-review fields, `gmail_handoff_reviewed: true`, and the returned Gmail draft/message/thread IDs.

## Prepared Review Binding

`preflight_review` and `prepared_review` are local workflow guards. They are not a public security boundary, but future callers must treat them as required freshness checks.

- `/api/prepare/preflight` returns `preflight_review`.
- `/api/prepare` must receive the current `preflight_review` and returns `prepared_review`.
- `/api/gmail/manual-handoff`, `/api/gmail/drafts/create`, and prepared-payload `/api/drafts/record` require `prepared_manifest`, `prepared_review_token`, and `review_fingerprint`.
- Any source, intake, queue, packet-mode, payload, manifest, PDF, or attachment change makes the old prepared review stale.
- A stale or mismatched token must block before returning a handoff packet, calling Gmail, or writing local draft/duplicate records.

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

## Executable Smoke

Use the isolated smoke before changing this boundary:

```powershell
python scripts\isolated_app_smoke.py --adapter-contract-checks --json
```

It drives the future caller sequence through source upload, numbered-answer review recovery, packet preflight, prepare, Manual Draft Handoff, stale prepared-review rejection, and synthetic local draft recording in a temporary runtime. It must not contact Gmail or write to LegalPDF Translate.
- `write_allowed: false`
- `legalpdf_write_allowed: false`
- `managed_data_changed: false`

The reusable caller-shim starting point lives in `scripts/legalpdf_adapter_caller.py`. It exposes the safe endpoint list, reusable HTTP JSON/multipart transport, prepared-review request-field helpers, stale-token helpers, contract validation for the exact prepared-review binding fields, the injected synthetic adapter sequence used by the smoke runner, and a secret-free `AdapterSequenceResult.safe_summary()` for future callers that need readiness signals without copyable Gmail prompts or local payload paths.

For focused caller debugging against an already-running isolated app, the shim also has a guarded CLI:

```powershell
python scripts\legalpdf_adapter_caller.py --base-url http://127.0.0.1:8766 --allow-synthetic-recording --json
```

The flag is intentionally explicit because the full sequence prepares synthetic artifacts and records synthetic draft IDs. Use the isolated smoke launcher for normal verification.

Use that endpoint as the machine-readable source for future LegalPDF integration planning.
