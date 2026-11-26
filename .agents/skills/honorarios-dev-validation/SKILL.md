---
name: honorarios-dev-validation
description: >-
  Antigravity runbook for validating LegalPDF Honorários with the pinned
  .venv311 environment, focused test groups, isolated synthetic servers,
  browser verification, and public-repo privacy gates.
---

# Honorários Development & Validation (Antigravity)

Use this skill when modifying code, tests, docs, or UI in LegalPDF Honorários.

## 1. Environment & Focused Test Groups

Always use the pinned `.venv311` interpreter (`3.11.9`) and `uv==0.12.20` lock (`uv.lock`). Never run tests with global Python or upgrade dependencies during routine work.

```powershell
# Read-only environment and doc-routing checks
.\.venv311\Scripts\python.exe scripts/check_dev_environment.py --json
.\.venv311\Scripts\python.exe scripts/check_project_docs.py

# Focused portable test groups (runs inside an isolated temporary checkout)
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group quick
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group intake
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group quality
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group pdf
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group email
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group ui
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group package
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Group integration
```

Run full validation before proposing completion or merges:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate_dev.ps1 -Full
```

## 2. Isolated Synthetic Runtime & Browser Verification

Never run artifact-writing checks against the live `config/`, `data/`, or `output/` directories. Start a disposable isolated server on a free port using a new/empty directory:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_dev.ps1 -RuntimeRoot .tmp-test/agy-verify -Synthetic -Port 8891
```

- In Antigravity, verify live UI flows using the `browser` subagent or Playwright MCP against `http://127.0.0.1:8891/`, or use API-level isolated smokes (`.\.venv311\Scripts\python.exe scripts/isolated_app_smoke.py --source-upload-checks --json`, etc.).
- Do NOT try to run Codex's `js_repl` / Atlas `scripts/browser_iab_smoke.mjs` in Antigravity (those require Codex's proprietary Atlas browser runtime).
- Clean up `.tmp-test/...` after stopping the synthetic server.

## 3. Public-Repo Privacy Gates & Test-Slicing Invariants

Before staging or committing:

```powershell
.\.venv311\Scripts\python.exe scripts/public_repo_gate.py --hook-configured --json
.\.venv311\Scripts\python.exe scripts/public_repo_gate.py --tracked --json
.\.venv311\Scripts\python.exe scripts/public_repo_gate.py --staged --json
.\.venv311\Scripts\python.exe scripts/evaluate_source_quality.py
```

Keep these test invariants intact when editing code:
1. Adding/removing portable test files requires updating **4 files in lockstep**: `tests/portable-suite.txt`, `tests/portable-groups.json`, `scripts/run_portable_tests.py` (`PUBLIC_TEST_FILES`), and `tests/test_portable_groups.py` (`EXPECTED`).
2. In `honorarios_app/static/app.js`, keep `\nbindNavigation();`, single-line `#gmail-sent-sync-now` / `#gmail-sent-sync-enable` listeners, and sliced function header boundaries intact.
3. In `honorarios_app/static/camera_picker.js`, never assign `innerHTML`.
4. In `honorarios_app/static/style.css`, keep the final `@media (max-width: 760px)` block containing the mobile action-rail/button assertions intact.
