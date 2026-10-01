# Development runbook

This is the standalone LegalPDF Honorários project. Develop the interpreting fee-request workflow here until a separately reviewed LegalPDF Translate adapter is ready.

## Start a session

1. Read the local `AGENTS.md` when present. It is intentionally ignored and contains operational and private-data guardrails.
2. Read [current handoff](docs/next-thread-handoff.md), then [app knowledge](APP_KNOWLEDGE.md).
3. Use the [environment guide](docs/development-environment.md) and [validation guide](docs/validation.md) for setup and checks.
4. The [authorized publication contract](docs/assistant/exec_plans/completed/2026-10-01_readiness_publication.md) governs PR/check/merge/cleanup; actual PR state and its receipt establish completion. The [completed three-source live draft run](docs/assistant/exec_plans/completed/2026-10-01_three_source_live_acceptance.md) records the subsequent actual Gmail acceptance. The [completed three-source review](docs/assistant/exec_plans/completed/2026-10-01_three_source_review.md) and its current handoff record local acceptance. The completed [readiness goal](docs/assistant/exec_plans/completed/2026-10-01_readiness_goal_completion.md), including unfinished-work resume and protected backup acceptance, is the preceding checkpoint. The earlier [whole-app audit](docs/assistant/exec_plans/completed/2026-10-01_app_readiness_audit.md), [source-email grouping plan](docs/assistant/exec_plans/completed/2026-10-01_source_email_groups.md), [live draft acceptance plan](docs/assistant/exec_plans/completed/2026-10-01_live_draft_acceptance.md), [email-routing plan](docs/assistant/exec_plans/completed/2026-10-01_email_routing.md), [claim-options plan](docs/assistant/exec_plans/completed/2026-10-01_claim_options_shared_trip.md), [six-case photo plan](docs/assistant/exec_plans/completed/2026-09-30_six_case_photo_acceptance.md), [photo defaults](docs/assistant/exec_plans/completed/2026-09-30_photo_defaults.md), [source decision quality](docs/assistant/exec_plans/completed/2026-09-30_source_decision_quality.md) and [foundation plan](docs/assistant/exec_plans/completed/2026-09-30_development_foundation.md) preserve historical acceptance. The actual GitHub PR/current-head checks identified by the handoff govern publication. Use the [small plan lifecycle](docs/assistant/exec_plans/PLANS.md) for substantial changes.
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
