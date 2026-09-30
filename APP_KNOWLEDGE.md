# LegalPDF Honorários app knowledge

LegalPDF Honorários creates Portuguese PDF fee requests for in-person interpreting services. It is a separate development project intended for future integration with LegalPDF Translate. Translation/word-count requests are set aside.

## Architecture and ownership

| Layer | Entry points and responsibilities |
| --- | --- |
| Browser/API | `honorarios_app/web.py`, templates and static assets: source intake, review, numbered answers, PDF preview, batch queue, draft handoff, profiles and references. |
| Shared application services | `honorarios_app/services.py`: coordinates review, preparation, freshness binding, managed data, backups and adapter boundaries. |
| Domain/CLI helpers | `scripts/`: authoritative PDF generation, classification, dates/questions, duplicate identity, recipient validation, packet preparation and local draft recording. |
| Runtime isolation | `honorarios_app/runtime.py`: separates config/data/output paths and initializes disposable synthetic fixtures for checks. |
| Optional providers | AI recovery, Google Photos and Gmail helpers: local configuration, secret-free status, guarded provider operations. |
| Future caller | `scripts/legalpdf_adapter_caller.py` and `/api/integration/adapter-contract`: versioned endpoint sequence and caller validation. |

The browser and CLI share the domain rules. Packaging must include the shared helpers, templates and static assets; an installed import alone is insufficient proof that the workflow works.

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

The September preparation work adds a pinned development environment, locked setup/validation commands, package checks, and concise documentation front doors. Local isolated Full validation passed 91 portable synthetic tests (including actual installed-wheel checks) and four isolated workflow smokes. Application to the original checkout and hosted-check status are recorded separately in the [current handoff](docs/next-thread-handoff.md).

Daily use is supported from the source checkout. Installed-wheel validation uses an explicit isolated runtime root; configuring an installed distribution's private default runtime is deferred. Future main-app orchestration and production integration acceptance remain separate work.

Use the [integration readiness guide](docs/integration-readiness.md) for the boundary and remaining acceptance criteria, not older roadmap feature inventories.
