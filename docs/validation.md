# Validation

Run project checks using the locked project environment. Protect private data by keeping artifact-writing checks inside disposable synthetic runtimes.

## Default and full checks

From the source-checkout root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Full
```

The default wrapper checks the pinned environment, lock/export consistency, dependency compatibility, documentation links, JavaScript syntax and public synthetic tests through `scripts/run_portable_tests.py`. The runner selects only the explicitly listed files in `tests/portable-suite.txt`, then runs them in a temporary source-only checkout with no private overlays. It includes the actual installed-wheel smoke.

`-Full` additionally exercises isolated source-upload, supporting-proof, adapter-contract and fake-Gmail API smoke. Run it before proposing integration readiness, a merge, or changes to code/tests/workflows/dependencies. Report the executed checks and their actual results; do not infer success from command availability.

## Work in focused chunks

While changing one behavior, select its public test group instead of repeatedly rebuilding and checking every unrelated workflow:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group quick
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group intake
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group quality
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group ui
.\.venv311\Scripts\python.exe scripts/run_portable_tests.py --group pdf
```

The accepted groups are `quick`, `intake`, `quality`, `pdf`, `email`, `ui`, `package`, `integration` and `full`. Their exact membership lives in `tests/portable-groups.json`; every selected test file must also belong to the explicit public allowlist in `tests/portable-suite.txt`. Unknown groups or unsafe/unlisted entries must fail. Group selection retains the temporary source-only checkout and provider-environment stripping.

The `quality` group runs fictional source-decision oracles, saved photo-default regressions and evaluator safeguards. Run `.\.venv311\Scripts\python.exe scripts/evaluate_source_quality.py` for the repeatable scorecard. It measures decision handling from provided text/provider replay, not OCR or private-document accuracy. Actual paid model and image-reading acceptance requires an explicitly authorized bounded session, using fictional sources by default; see [the model comparison](source-quality.md). Record any separately authorized real-source exception in the plan and handoff, and retain its source/results only in ignored local evidence.

Use `quick` for a fast general checkpoint, then the group matching the changed behavior. Intake covers request/review rules, PDF covers document generation, email covers recipient/draft rules, UI covers browser-facing behavior, package covers distribution, and integration covers the adapter/workflow boundary. The wrapper also runs environment/docs/JavaScript checks for the selected group; the direct Python runner runs that group alone.

With no group selected, both commands keep the full public suite as their default. `-Full` requires the `full` group and adds the four isolated workflow smokes. Run it on the final integrated branch; a quick/group pass does not replace final Full or the [browser/PDF acceptance checklist](workflow-acceptance.md). Repeat broader checks when subsequent changes or failures justify them.

Useful focused commands:

```powershell
.\.venv311\Scripts\python.exe scripts/check_dev_environment.py --json
.\.venv311\Scripts\python.exe scripts/run_portable_tests.py
node --check honorarios_app/static/app.js
node --check honorarios_app/static/review_guidance.js
node --check scripts/browser_iab_smoke.mjs
.\.venv311\Scripts\python.exe scripts/installed_wheel_smoke.py --json
```

The legacy runtime doctor checks broader runtime/dependency drift. It complements the pinned development checker; it does not replace it.

## Isolated workflow checks

```powershell
.\.venv311\Scripts\python.exe scripts/isolated_app_smoke.py --source-upload-checks --json
.\.venv311\Scripts\python.exe scripts/isolated_app_smoke.py --supporting-attachment-checks --json
.\.venv311\Scripts\python.exe scripts/isolated_app_smoke.py --adapter-contract-checks --json
.\.venv311\Scripts\python.exe scripts/isolated_app_smoke.py --gmail-api-checks --json
```

These checks use disposable runtime roots and synthetic fixtures. The adapter check covers source intake, numbered answers, preflight, preparation, Manual Draft Handoff, review-token binding/stale rejection and synthetic local draft recording. The fake-Gmail check never contacts Google. Neither check writes to LegalPDF Translate.

Optional Browser/IAB or Playwright checks remain documented in [the roadmap/process references](process-optimizations.md). Use the [workflow acceptance checklist](workflow-acceptance.md) for the actual guided journey and rendered PDF. Run any artifact-writing browser path through the isolated launcher. If the adapter lacks a required capability, record the tooling blocker; do not substitute private files or real draft records.

## Tracked-content privacy checks

Before a commit or public update, stage paths explicitly and run:

```powershell
.\.venv311\Scripts\python.exe scripts/public_repo_gate.py --hook-configured --json
.\.venv311\Scripts\python.exe scripts/public_repo_gate.py --staged --json
.\.venv311\Scripts\python.exe scripts/public_repo_gate.py --tracked --json
```

The existing local hook is a separate configuration check. A fresh worktree must not silently change shared Git configuration or stage unrelated work to satisfy it.

`scripts/public_release_gate.py` inspects a whole directory. The live checkout intentionally contains ignored private overlays, so a full-tree privacy failure there can be expected. Use that stricter gate for a separately requested sanitized candidate; it is not the default contribution gate and does not authorize publication.

## Live and production acceptance

For a multi-case source, exercise case switching, unresolved/edited rows, fresh review, atomic bulk queueing and preservation of earlier sources. Check each case's own evidence and duplicate identity. Prepare separate PDFs and inspect every rendered page for its own case/date/payer/venue/travel facts. In mixed-city batches, the prepared summary must come from the prepared snapshot even when another source case is selected. Capture-day, payer-court and missing-venue court preferences are user policies, not proof of printed facts. The [completed six-case acceptance](assistant/exec_plans/completed/2026-09-30_six_case_photo_acceptance.md) records the bounded actual-source exception, provider-call/replay distinction and final 330-test checks; routine tests remain fictional and isolated.

A read-only smoke of an already-authorized running fee app may use its actual base URL, such as `http://127.0.0.1:8878`. Check ownership and health first. Do not assume the historical `8765` URL belongs to this app.

Real Gmail/provider calls, profile imports/restores, visual review of real generated PDFs, and production main-app orchestration are separate acceptance work. Synthetic success does not establish those outcomes. Record current check results and deferred work in [the handoff](next-thread-handoff.md).
