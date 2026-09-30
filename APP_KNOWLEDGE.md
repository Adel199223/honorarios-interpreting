# LegalPDF Honorários app knowledge

LegalPDF Honorários creates Portuguese PDF fee requests for in-person interpreting services. It is a separate development project intended for future integration with LegalPDF Translate. Translation/word-count requests are set aside.

## Architecture and ownership

| Layer | Entry points and responsibilities |
| --- | --- |
| Browser/API | `honorarios_app/web.py`, templates and static assets: source intake, review, numbered answers, PDF preview, batch queue, draft handoff, profiles and references. |
| Browser review guidance | `honorarios_app/static/review_guidance.js`: pure guided-step, question and outcome helpers; rendering/action gates remain in `app.js`. |
| Shared application services | `honorarios_app/services.py`: compatibility facade plus runtime/provider/domain orchestration, review, preparation, freshness binding, managed data, backups and adapter boundaries. |
| Source evidence | `honorarios_app/source_evidence.py`: pure field provenance, profile evidence, Review Attention and text/metadata helpers; no file or provider operations. |
| Domain/CLI helpers | `scripts/`: authoritative PDF generation, classification, dates/questions, duplicate identity, recipient validation, packet preparation and local draft recording. |
| Runtime isolation | `honorarios_app/runtime.py`: separates config/data/output paths and initializes disposable synthetic fixtures for checks. |
| Optional providers | AI recovery, Google Photos and Gmail helpers: local configuration, secret-free status, guarded provider operations. |
| Future caller | `scripts/legalpdf_adapter_caller.py` and `/api/integration/adapter-contract`: versioned endpoint sequence and caller validation. |

The browser and CLI share the domain rules. The services facade retains existing evidence exports so extraction does not change routes, payloads, dates, duplicate checks, recipients or freshness binding. Packaging must include the shared helpers, templates and static assets; an installed import alone is insufficient proof that the workflow works.

## Managed data

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

## Current preparation status

The September preparation work adds a pinned development environment, locked setup/validation commands, package checks, and concise documentation front doors. The preparation-only publication branch passed 89 portable synthetic tests (including actual installed-wheel checks), four isolated workflow smokes, and hosted Windows/GitHub Full validation. The original saved checkout passed 91 tests because it also retains separate local interface work. Publication and application evidence are recorded in the [current handoff](docs/next-thread-handoff.md).

Daily use is supported from the source checkout. Installed-wheel validation uses an explicit isolated runtime root; configuring an installed distribution's private default runtime is deferred. Future main-app orchestration and production integration acceptance remain separate work.

Use the [integration readiness guide](docs/integration-readiness.md) for the boundary and remaining acceptance criteria, not older roadmap feature inventories.

## Current development foundation

The [source decision quality plan](docs/assistant/exec_plans/completed/2026-09-30_source_decision_quality.md) is complete locally and applied to the saved app, from published main `f792c95` (PR #59 merged). It repairs contextual dates/locations, classification, physical-host PDF wording, honest AI evidence and the five-fact beginner review. Source recovery now defaults to gpt-6.1-sol/high; the intended saved AI settings select it. Final Full passed 256 public synthetic tests and four isolated workflows in the candidate and saved checkout, plus actual fictional PDF/photo, date-confirmation, stale-edit, rendered-PDF and manual-handoff checks. The 39 labelled decision cases pass; a six-source/three-model actual comparison passed for every candidate, with measured costs and limitations in [source quality](docs/source-quality.md). The user authorized publication and merge on 2026-09-30; [PR #60](https://github.com/Adel199223/honorarios-interpreting/pull/60) is the authoritative publication/check/merge record for this scope. The foundation acceptance below is historical.

The published environment baseline is PR #58, merged at `bb9b1cf`. The development foundation starts from that baseline and recovers the saved guided interface locally. It adds focused public test groups, bounded code organization, the [plan lifecycle](docs/assistant/exec_plans/PLANS.md), [workflow acceptance checklist](docs/workflow-acceptance.md) and [beginner user guide](docs/user-guide.md).

The guided path leads with one source upload, recovered-fact review, prominent numbered questions, Portuguese draft/PDF preview and Manual Draft Handoff. Advanced intake, batch, evidence and provider controls remain available behind explicit details. Capture-date suggestions are evidence and require service-date confirmation.

This foundation is complete locally and applied to the saved development checkout. Final Full validation passed 164 public synthetic tests and four isolated workflows in both the review build and saved checkout; launch preflight passed. Actual browser PDF/photo intake, numbered answers, explicit capture-date confirmation, visible fallback warning, generated PDF inspection, manual handoff, stale attachment clearing, reset, disconnection and desktop/mobile keyboard review passed with fictional data. The [completed plan](docs/assistant/exec_plans/completed/2026-09-30_development_foundation.md) and [current handoff](docs/next-thread-handoff.md) record evidence and failed attempts.

Publication is tracked in [PR #59](https://github.com/Adel199223/honorarios-interpreting/pull/59); the user authorized publication and merge after final checks pass. The PR's current merge/check status establishes GitHub main availability. Main-app orchestration, real documents/providers and installed private-default runtime configuration remain separate acceptance. The tested dependency pins remain in use; no additional plugin or setting change was needed.
