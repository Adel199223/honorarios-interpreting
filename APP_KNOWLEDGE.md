# LegalPDF Honorários app knowledge

LegalPDF Honorários creates Portuguese PDF fee requests for in-person interpreting services. It is a separate development project intended for future integration with LegalPDF Translate. Translation/word-count requests are set aside.

## Architecture and ownership

| Layer | Entry points and responsibilities |
| --- | --- |
| Browser/API | `honorarios_app/web.py`, templates and static assets: source intake, review, numbered answers, PDF preview, batch queue, draft handoff, profiles and references. |
| Browser review guidance | `honorarios_app/static/review_guidance.js`: pure guided-step, question and outcome helpers; rendering/action gates remain in `app.js`. |
| Shared application services | `honorarios_app/services.py`: compatibility facade plus runtime/provider/domain orchestration, review, preparation, freshness binding, managed data, backups and adapter boundaries. |
| Source evidence | `honorarios_app/source_evidence.py`: pure field provenance, profile evidence, Review Attention and text/metadata helpers; no file or provider operations. |
| Source cases | `honorarios_app/source_cases.py`: source-grounded case references, ordered deduplication and ambiguity/administrative-reference checks; services review each child independently. |
| Domain/CLI helpers | `scripts/`: authoritative PDF generation, classification, dates/questions, duplicate identity, recipient validation, packet preparation and local draft recording. |
| Runtime isolation | `honorarios_app/runtime.py`: separates config/data/output paths and initializes disposable synthetic fixtures for checks. |
| Optional providers | AI recovery, Google Photos and Gmail helpers: local configuration, secret-free status, guarded provider operations. |
| Future caller | `scripts/legalpdf_adapter_caller.py` and `/api/integration/adapter-contract`: versioned endpoint sequence and caller validation. |

The browser and CLI share the domain rules. The services facade retains existing evidence exports so extraction does not change routes, payloads, dates, duplicate checks, recipients or freshness binding. Packaging must include the shared helpers, templates and static assets; an installed import alone is insufficient proof that the workflow works.

## Managed data

- Ignored `config/photo-defaults.local.json` optionally supplies the user's capture-day/service-day and capture-city/local-court policy. `honorarios_app/photo_defaults.py` applies it after photo reading, retains provenance and coherent routing through re-review; unresolved photo routing cannot use the general email fallback. See [source quality](docs/source-quality.md#saved-photo-defaults).
- Personal profiles contain the applicant/payment/address/travel information. The selected profile is adapted into the existing generator profile contract.
- Service profiles contain recurring interpreting service/payment/recipient patterns.
- Duplicate records and draft lifecycle records protect both drafted and sent requests; packet requests retain their underlying identities.
- Prepared PDF/payload/manifest files and review tokens belong to the same reviewed request snapshot. Source, intake, queue, profile or attachment changes invalidate that snapshot.
- Private overlays, tokens, source documents, generated output, backups and reports remain local and ignored. Public fixtures and tests must be synthetic.

Future integrations must use the app boundary rather than directly edit these files.

## Workflow and safety

The normal sequence is source intake -> review -> numbered answers -> non-writing preflight -> PDF preparation and preview -> Manual Draft Handoff -> local recording of returned draft IDs. Missing Gmail OAuth does not block the manual handoff workflow.

Optional direct Gmail creation calls only `users.drafts.create` after current PDF/payload review, duplicate checks and acknowledgement. Verification calls only `users.drafts.get`. The app does not send email or offer mailbox search/trash/delete operations. The user reviews and sends drafts manually.

LegalPDF reference import previews and plans are read-only. Existing apply/restore paths require their exact confirmation phrase and reason, create backups, and write only this app's permitted reference files. They do not write to LegalPDF Translate.

## Email recipients and prepared selection

The normal review includes a saved court email picker beside the editable recipient. Selecting a contact clears stale contact aliases and exception reasons, then runs the existing review without changing payer or service venue. Routing independently validates the paying court; exact local matches precede broader aliases and equally plausible conflicting contacts pause. Source recovery selects a contact automatically only when the combined visible source text contains one unique email. Explicit saved or manual choices remain valid subject to payer checks.

After preparation, **Email draft for** selects one immutable prepared case and shows its recipient and PDF. Copy, manual handoff, optional Gmail creation, returned-ID recording and lifecycle checks use that same prepared item. Changing selection clears per-target handoff/IDs/checklist and discards late results without changing PDFs or the manifest. A packet remains one target with existing all-child checks. Routes, payload contracts, signed freshness and draft-only behavior remain intact.

The [completed email-routing plan](docs/assistant/exec_plans/completed/2026-10-01_email_routing.md) preserves the earlier local-only acceptance: 422 tests/four isolated workflows in candidate and saved app, six cached-source handoffs, matching PDF text/pixels and local RFC email attachment bytes. It did not create actual Gmail drafts.

The subsequent [live acceptance plan](docs/assistant/exec_plans/completed/2026-10-01_live_draft_acceptance.md) records six actual unsent drafts created through ordinary saved-app controls and recorded in canonical history. Six returned-ID UI verifications and independent raw reads matched recipient, subject, body and one own PDF's exact bytes; every message retained `DRAFT` without `SENT`. Shared travel stayed on one request. An initial rejected OAuth refresh made zero create POSTs; a normal same-client/same-scope reconnect and fresh guarded preparation resolved it without a blind retry or new OpenAI read. Failure-card wording now distinguishes confirmed creation from unconfirmed outcomes. At the live-acceptance checkpoint, candidate and saved Full each passed 423 tests and four isolated workflows. Final closeout retained existing history rows, unrelated protected settings and original results, with exact mutable-file beforeimages and safe server/browser cleanup. The [current handoff](docs/next-thread-handoff.md) identifies the publication candidate; the actual GitHub PR/current-head checks determine merge status. Sending and main-app integration remain outside this work.

The first hosted [PR #61](https://github.com/Adel199223/honorarios-interpreting/pull/61) run then exposed a Node-test decoding mismatch between Windows defaults and UTF-8 CI. Only test-harness decoding and equivalent escape notation changed; a simulated Windows-default regression now covers that boundary. Final candidate and saved-app Full each passed 424 tests and four isolated workflows. The earlier 423-test checkpoint and live acceptance remain valid; the corrected current PR head requires hosted Full before merge.

## Current preparation status

The September preparation work adds a pinned development environment, locked setup/validation commands, package checks, and concise documentation front doors. The preparation-only publication branch passed 89 portable synthetic tests (including actual installed-wheel checks), four isolated workflow smokes, and hosted Windows/GitHub Full validation. The original saved checkout passed 91 tests because it also retains separate local interface work. Publication and application evidence are recorded in the [current handoff](docs/next-thread-handoff.md).

Daily use is supported from the source checkout. Installed-wheel validation uses an explicit isolated runtime root; configuring an installed distribution's private default runtime is deferred. Future main-app orchestration and production integration acceptance remain separate work.

Use the [integration readiness guide](docs/integration-readiness.md) for the boundary and remaining acceptance criteria, not older roadmap feature inventories.

## Current claim choices and shared trips

The [completed claim-options plan](docs/assistant/exec_plans/completed/2026-10-01_claim_options_shared_trip.md) adds interpreting-and-travel (normal default), interpreting-only and travel-only in ordinary review. Optional `claim_interpreting` defaults true for older callers; `claim_transport` retains its existing behavior. The generator rejects neither selected. Travel-only states attendance, requests solely transport, omits the interpreting-service tax wording and narrows the default email; explicit conflicting custom email text pauses.

Multi-case sources with consistent visit facts default to one explicit travel group and a selectable owner. Separately selected trips and no travel remain available. A stable source-hash group protects re-uploaded identical sources; altered photos and unmarked older history need manual checking. Services and direct CLI validate group facts/ownership before artifacts. Draft/packet/index metadata retains the binding and optional draft creation/local recording rechecks active recorded owners. Prepared artifacts alone do not reserve a trip. The case/date/period duplicate key and freshness contracts stay intact.

Final candidate and saved Full each passed 378 synthetic tests plus four isolated workflows. Real-source browser replay prepared six corrected requests with one shared travel claim; every rendered page and a fictional travel-only example passed root and independent inspection. Validated public files and touched docs are applied to the saved app, while private settings/records and dependency pins remain unchanged. Earlier per-case travel results are superseded with originals retained. This scope is complete locally and unpublished; no additional provider/Gmail action or main-app integration occurred. See the [current handoff](docs/next-thread-handoff.md) for exact evidence and boundaries.

## Historical multi-case photo acceptance

The [completed six-case plan](docs/assistant/exec_plans/completed/2026-09-30_six_case_photo_acceptance.md) extends the photo rules with the user's third preference: when a physical service venue is absent, use the capture-city court. An explicitly named source station or other physical host wins over that venue default. Defaults remain editable, distinct from source evidence and separately enabled in ignored preferences.

Several visible case references now produce separately reviewable requests on one immutable source. Invalid or ambiguous rows remain unresolved; administrative references cannot become cases. Normal review runs for every row before atomic bulk queueing. Corrections, duplicate collisions and stale preparation remain blocked, and changing sources preserves previously queued requests. Prepared summaries use the prepared request snapshot rather than a different currently selected source case.

The validated files and intended private photo-policy/contact changes are applied to the usual saved checkout. Final candidate and saved-checkout Full passed 330 public synthetic tests and four isolated workflows; saved launch preflight passed at 8878. Actual browser controls prepared six separate PDFs from the two authorized photos. Root and independent review accepted every rendered page; saved-import replay reached six ready requests without more provider calls. Five actual provider reads were used in total; later browser/replay runs reused their captured responses. The bounded handwritten comparison recovered the same five cases with Sol and Astra, so Sol/high remains the default. See [source quality](docs/source-quality.md) for timings, cost estimates and Decisions API limits.

Exactly two protected configuration entries changed: the public example and the intended ignored photo policy/verified city contact. The other 19 protected hashes, saved branch/history and unrelated private records remain unchanged. Exact beforeimages and private results remain ignored and local. The owned test server is stopped and temporary browser tab blank. This scope is complete locally and unpublished; no Gmail, draft/index record write or main-app integration occurred. Two photos do not establish production accuracy.

## Historical photo defaults

The [completed photo defaults plan](docs/assistant/exec_plans/completed/2026-09-30_photo_defaults.md) implements the user's standing photo policy: capture day is the interpreting day, and the court in the capture city is the payer. The policy is opt-in through local preferences; selected values remain editable and visibly labeled as defaults. Automatic profiles and source court names cannot replace the city rule. An explicitly selected service profile or later manual edit can supply an exception. Missing or competing capture information and missing court contacts still pause.

The changes and authorized local preferences are applied to the usual saved checkout. Final saved-checkout Full passed 285 public synthetic tests and four isolated workflows, including the bounded shared PDF grammar correction. One authorized read of the supplied partial photo took 28.45 seconds with gpt-6.1-sol/high; replay with the applied settings required no additional provider call. Astra independently accepted the regenerated final PDF and the routing, manual-edit and grammar fixes. The 19 pre-existing private JSON files and saved branch/history remain unchanged; launch preflight passed at 8878. This is acceptance of the supplied example, not a production accuracy estimate. The [current handoff](docs/next-thread-handoff.md) records the completed local scope. No Gmail action or publication was performed.

## Historical development foundation

The [source decision quality plan](docs/assistant/exec_plans/completed/2026-09-30_source_decision_quality.md) is complete locally and applied to the saved app, from published main `f792c95` (PR #59 merged). It repairs contextual dates/locations, classification, physical-host PDF wording, honest AI evidence and the five-fact beginner review. Source recovery now defaults to gpt-6.1-sol/high; the intended saved AI settings select it. Final Full passed 256 public synthetic tests and four isolated workflows in the candidate and saved checkout, plus actual fictional PDF/photo, date-confirmation, stale-edit, rendered-PDF and manual-handoff checks. The 39 labelled decision cases pass; a six-source/three-model actual comparison passed for every candidate, with measured costs and limitations in [source quality](docs/source-quality.md). The user authorized publication and merge on 2026-09-30; [PR #60](https://github.com/Adel199223/honorarios-interpreting/pull/60) is the authoritative publication/check/merge record for this scope. The foundation acceptance below is historical.

The published environment baseline is PR #58, merged at `bb9b1cf`. The development foundation starts from that baseline and recovers the saved guided interface locally. It adds focused public test groups, bounded code organization, the [plan lifecycle](docs/assistant/exec_plans/PLANS.md), [workflow acceptance checklist](docs/workflow-acceptance.md) and [beginner user guide](docs/user-guide.md).

The guided path leads with one source upload, recovered-fact review, prominent numbered questions, Portuguese draft/PDF preview and Manual Draft Handoff. Advanced intake, batch, evidence and provider controls remain available behind explicit details. Capture-date suggestions are evidence and require service-date confirmation.

This foundation is complete locally and applied to the saved development checkout. Final Full validation passed 164 public synthetic tests and four isolated workflows in both the review build and saved checkout; launch preflight passed. Actual browser PDF/photo intake, numbered answers, explicit capture-date confirmation, visible fallback warning, generated PDF inspection, manual handoff, stale attachment clearing, reset, disconnection and desktop/mobile keyboard review passed with fictional data. The [completed plan](docs/assistant/exec_plans/completed/2026-09-30_development_foundation.md) and [current handoff](docs/next-thread-handoff.md) record evidence and failed attempts.

Publication is tracked in [PR #59](https://github.com/Adel199223/honorarios-interpreting/pull/59); the user authorized publication and merge after final checks pass. The PR's current merge/check status establishes GitHub main availability. Main-app orchestration, real documents/providers and installed private-default runtime configuration remain separate acceptance. The tested dependency pins remain in use; no additional plugin or setting change was needed.
