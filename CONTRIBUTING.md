# Contributing

Use synthetic fixtures only. Do not commit real case numbers, court email addresses, Gmail draft IDs, generated PDFs, source screenshots, IBANs, addresses, or local API keys.

Use [the locked development setup](docs/development-environment.md) and [the validation guide](docs/validation.md). Preserve existing local edits and use an isolated worktree for concurrent or substantial changes. Keep routine changes on the current locked package versions.

Use a bounded [active plan and lifecycle](docs/assistant/exec_plans/PLANS.md) for multi-file/workflow changes. Define the behavior being changed, run its focused test group during development, and use the [workflow acceptance checklist](docs/workflow-acceptance.md) for browser/PDF behavior. A markup check alone does not establish that a user can complete the workflow.

For fast iteration, use `scripts/validate_dev.ps1 -Group quick` or select `intake`, `pdf`, `email`, `ui`, `package` or `integration` for the affected behavior. Selection stays within the public synthetic allowlist and isolated test checkout. Preserve the final Full checks below.

Before proposing a code/test/workflow/dependency change or a merge, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Full
.\.venv311\Scripts\python.exe scripts/public_repo_gate.py --hook-configured --json
.\.venv311\Scripts\python.exe scripts/public_repo_gate.py --tracked --json
```

Stage only intended paths and run `scripts/public_repo_gate.py --staged --json` with the project interpreter before committing. A full-workspace `public_release_gate` can block on intentionally ignored private overlays; reserve that stricter check for a separately requested sanitized candidate. Do not silently change shared hook configuration to satisfy a fresh-worktree check.

Update only affected documentation using [the runbook](agent.md); record actual results and remaining acceptance work in the handoff. No public change, deployment, live provider operation or main-app integration follows automatically from preparation checks.

The Gmail workflow is draft-only. Do not add UI, API, scripts, or tests that send email automatically. Preserve the [adapter contract](docs/legalpdf-adapter-contract.md) and execute artifact-writing checks only in disposable synthetic runtimes.
