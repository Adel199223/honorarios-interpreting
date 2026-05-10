# LegalPDF Adapter Contract

This contract describes how a future LegalPDF Translate integration should call the standalone LegalPDF Honorários workflow without copying its internals or bypassing its safety rules.

Current contract version: `2026-05-10.optional-gmail-boundary.v4`

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
- The nested `gmail_boundary` must remain explicit: `required_tool: "_create_draft"`, `draft_only: true`, and `send_allowed: false`.
- Future callers should reject the contract if that nested Gmail boundary is missing or advertises any send-capable behavior, even when the top-level contract remains `send_allowed: false`.

## Optional Gmail Draft API Boundary

Manual Draft Handoff remains the required and always-available sequence for LegalPDF callers. The app may also expose an optional OAuth-backed helper for local users, but callers must treat it as a separate, guarded draft-only path rather than as a replacement for the required sequence.

The machine-readable `optional_gmail_draft_api_boundary` describes that optional path:

- `create_endpoint: "/api/gmail/drafts/create"` may call only Gmail `users.drafts.create`.
- `verify_endpoint: "/api/gmail/drafts/verify"` may call only Gmail `users.drafts.get` and must stay read-only.
- `draft_only: true`, `send_allowed: false`, and `verify_read_only: true` are required.
- `verify_local_records_changed: false` is required because verification must not write duplicate records, draft logs, reference data, or Gmail state.
- `forbidden_actions` must include Gmail send, draft-send, message trash/delete/list, and draft delete actions.
- Draft creation still requires the current `prepared_review` fields from `/api/prepare`, including the reviewed handoff acknowledgement. Duplicate and active-draft blockers must run before any Gmail network call.

The reusable caller shim validates this optional boundary when the contract advertises it. Absence of this optional object does not make the Manual Draft Handoff contract invalid, and `/api/gmail/drafts/create` plus `/api/gmail/drafts/verify` must not be added to the required endpoint sequence.

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

Use the read-only caller readiness probe before changing this boundary or wiring a future LegalPDF caller:

```powershell
python scripts\legalpdf_adapter_caller.py --base-url http://127.0.0.1:8765 --readiness-only --json
```

That probe checks `/api/health` and this adapter contract only. It must not upload sources, prepare PDFs, record drafts, expose local paths, or call Gmail.

Then use the isolated smoke for the full synthetic sequence:

```powershell
python scripts\isolated_app_smoke.py --adapter-contract-checks --json
```

It drives the future caller sequence through source upload, numbered-answer review recovery, packet preflight, prepare, Manual Draft Handoff, stale prepared-review rejection, and synthetic local draft recording in a temporary runtime. It must not contact Gmail or write to LegalPDF Translate.

The reusable full-sequence caller also verifies `/api/health` before upload and refuses to continue unless the server attests `isolated_runtime=true`, `synthetic_runtime=true`, and the expected synthetic runtime marker. `--readiness-only` remains the safe live-app probe because it is read-only.
- `write_allowed: false`
- `legalpdf_write_allowed: false`
- `managed_data_changed: false`

The reusable caller-shim starting point lives in `scripts/legalpdf_adapter_caller.py`. It exposes the safe endpoint list, `/api/health` readiness probing, reusable HTTP JSON/multipart transport, `AdapterSourceInput` for caller-supplied sanitized in-memory source uploads, prepared-review request-field helpers, stale-token helpers, contract validation for the exact prepared-review binding fields, the generic `run_adapter_sequence_result(...)` / `run_adapter_sequence_http(...)`, the synthetic adapter sequence wrapper used by the smoke runner, and secret-free `AdapterReadinessResult.safe_summary()` / `AdapterSequenceResult.safe_summary()` outputs for future callers that need readiness signals without copyable Gmail prompts, uploaded source bytes, source filenames, or local payload paths.

For focused caller debugging against an already-running isolated app, the shim also has a guarded artifact-writing CLI:

```powershell
python scripts\legalpdf_adapter_caller.py --base-url http://127.0.0.1:8765 --allow-synthetic-recording --json
```

The same guarded CLI can exercise a caller-supplied sanitized source instead of the built-in synthetic PDF fixture:

```powershell
python scripts\legalpdf_adapter_caller.py --base-url http://127.0.0.1:8765 --source-file .\tmp\sanitized-legalpdf-source.pdf --source-kind notification_pdf --case-number 321/26.0CALLER --service-date 2026-05-06 --allow-synthetic-recording --json
```

The flag is intentionally explicit because the full sequence prepares artifacts and records synthetic draft IDs, and the caller still refuses to continue unless `/api/health` attests an isolated synthetic runtime. Use the isolated smoke launcher for normal verification.

Use that endpoint as the machine-readable source for future LegalPDF integration planning.
