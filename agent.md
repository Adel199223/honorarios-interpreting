# Development runbook

This is the standalone LegalPDF Honorários project. Develop the interpreting fee-request workflow here until a separately reviewed LegalPDF Translate adapter is ready.

## Start a session

1. Read the local `AGENTS.md` when present. It is intentionally ignored and contains operational and private-data guardrails.
2. Read [current handoff](docs/next-thread-handoff.md), then [app knowledge](APP_KNOWLEDGE.md).
3. Use the [environment guide](docs/development-environment.md) and [validation guide](docs/validation.md) for setup and checks.
4. Review the latest completed [six-case photo plan](docs/assistant/exec_plans/completed/2026-09-30_six_case_photo_acceptance.md) and its publication status in the current handoff. The [photo defaults](docs/assistant/exec_plans/completed/2026-09-30_photo_defaults.md), [source decision quality](docs/assistant/exec_plans/completed/2026-09-30_source_decision_quality.md) and [foundation plan](docs/assistant/exec_plans/completed/2026-09-30_development_foundation.md) remain historical acceptance. Use the [small plan lifecycle](docs/assistant/exec_plans/PLANS.md) for substantial changes.
5. For workflow work, use the [acceptance checklist](docs/workflow-acceptance.md) and [beginner user guide](docs/user-guide.md). For integration work, read [integration readiness](docs/integration-readiness.md) and the existing [adapter contract](docs/legalpdf-adapter-contract.md).

The machine-readable documentation map is [docs/assistant/manifest.json](docs/assistant/manifest.json).

## Work boundaries

- Preserve existing local edits. Use an isolated branch/worktree for concurrent or substantial changes; do not change the primary checkout's branch while its server is running.
- Preserve the locked dependency set during routine work. Reconstruct a candidate environment in isolation before changing a working environment. Do not use global Python for project tests or run unlocked dependency upgrades.
- Keep domain rules in the shared service/CLI layer. Browser routes and future callers must use those rules rather than introduce a second PDF, duplicate, date, recipient, or Gmail implementation.
- Preserve the existing route/payload contracts, freshness tokens, explicit review acknowledgements, and safe dynamic-text rendering unless the task specifically requires a reviewed contract change.
- Run artifact-writing smoke only against isolated synthetic runtime data. Do not test using private config, records, PDFs, source uploads, or real Gmail IDs.
- Work in bounded chunks: define the changed behavior, run its relevant focused test group, and inspect that user-flow step. Run Full validation once the final branch is integrated; repeat broader checks when new changes or failures justify them.
- Publishing, live Gmail/provider operations, private-data imports/restores, destructive operations, and integration into LegalPDF Translate need explicit task scope. Preparing this project does not authorize those actions.

## Keep documentation synchronized

Update only guidance affected by the change. Keep environment commands, validation, ownership, integration status, user guidance and the current handoff coherent. Preserve prior handoff/history and exact beforeimages when replacing current guidance. This is a small project harness; do not copy the main app's template system wholesale or add plugins/settings merely to match another project.

Record the exact checks actually run, their outcomes, skipped optional tooling, and remaining work. A documented command, dependency lock, package build, or isolated worktree alone does not establish that the application is validated or integrated.
