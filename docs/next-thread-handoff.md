# Next Thread Handoff

## Current preparation: 2026-09-30

The preparation covers this separate fee-request app's development environment, documentation and integration boundary for a future LegalPDF Translate integration. On 2026-09-30 the user approved publishing the preparation-only update and merging after GitHub checks pass. Main-app integration and live Gmail remain separate work.

- Original working branch: `codex/beginner-guided-intake-ux`, based on `a0ef9e1`, with fifteen pre-existing locally modified files. Preserve that development work.
- Preparation is performed in isolated worktrees. Prior local changes and document beforeimages are retained before applying preparation changes.
- Daily source-checkout setup uses Python `3.11.9`, uv `0.12.20`, Node `24.14.0` and the locked `.venv311` environment. The previous global Python environment and its package versions are preserved.
- The development launch helper uses `127.0.0.1:8878` to coexist with the main app. It preserves the application's historical direct-launch default and existing contracts.
- See [development environment](development-environment.md), [validation](validation.md), [app knowledge](../APP_KNOWLEDGE.md), [integration readiness](integration-readiness.md), and [runbook](../agent.md). The existing [adapter contract](legalpdf-adapter-contract.md) remains authoritative.
- Source-checkout use is the supported daily workflow. Installed-wheel checks exercise an explicit isolated runtime root; private default-runtime setup for an installed distribution remains deferred.
- Isolated validation: locked setup and independent environment reconstruction passed; 37 distributions are installed including this app and development tooling, with all 29 observed runtime package versions preserved. Full passed 91 portable synthetic tests, JavaScript syntax, lock/export compatibility, documentation routing, real offline installed-wheel verification and four isolated source/proof/adapter/fake-Gmail smokes.
- A complete separate uv-managed Python 3.11.9 was provisioned after the old installation was found missing a standard-library file. The initial uv install reported a minor-version-link error; subsequent direct integrity checks and uv interpreter discovery confirmed the complete installation. The first authoring environment and failed check logs are preserved. Old Python environments were not repaired/replaced.
- Initial Full attempts exposed an outdated startup-documentation expectation and slow full-workspace scanning of new environments. The repaired scanner prunes environment/worktree directories while still blocking their inclusion in whole-tree releases. Portable tests now run from an allowlisted temporary source checkout without private overlays; launch helpers refuse populated synthetic runtime paths.
- Application complete: the preparation files and dedicated `.venv311` are installed in the original saved checkout, retaining `codex/beginner-guided-intake-ux`. Saved-checkout Full independently passed the same 91 portable tests and four isolated smokes; launcher preflight passed at 8878. The application attempt exposed newline-only assertions in template/export parity tests; those now compare equivalent text across Windows line endings, and the bundled template matches the original source. Failed attempt logs are retained.
- Publication: the preparation-only update is published in [PR #58](https://github.com/Adel199223/honorarios-interpreting/pull/58). Hosted Windows/GitHub Full validation passed [run 186](https://github.com/Adel199223/honorarios-interpreting/actions/runs/36726038688) at `dc0d3af`; merge is authorized once the final checks pass. CircleCI/Linux, browser click-through and real document/provider acceptance remain unverified. The initial local application receipt is retained separately in ignored evidence.
- Future work: production LegalPDF caller/UI/process orchestration, reviewed private-data mapping, and real PDF/provider acceptance. Publication of the preparation-only scope is now approved; it excludes earlier interface work.

- Publication preflight (2026-09-30): the preparation-only delta was reconstructed on fresh `origin/main` (`a0ef9e1`) in `codex/fee-environment-preparation-20260930`. Its independent locked setup and Full validation passed 89 portable tests and four isolated workflow smokes. This scope excludes the earlier beginner-interface edits and local/private files. The earlier 91-test runs include that separate interface work. The user approved publication and merge after hosted checks pass. Hosted Windows/GitHub validation passed; the earlier interface work stays local. The preparation-only branch is the publication scope.

The May handoff below is preserved as historical context. Its old workspace placeholder, startup examples and public-branch description are not the current preparation authority.

## Historical handoff: 2026-05-10

Current date: 2026-05-10

## Project State

- Workspace and live public Git repo: `%USERPROFILE%/example-path`
- Public remote: `https://github.com/Adel199223/honorarios-interpreting`
- Public branch: `main`
- Public updates are committed from the root repo after the tracked Git safety gate passes.
- Real runtime data stays on this machine as ignored local overlays.
- `output/public-candidate` is now an optional sanitized audit/export candidate, not the primary publish checkout.

## App Status

- Local app command:

  ```powershell
  python -m honorarios_app.web --host 127.0.0.1 --port 8765
  ```

- Browser URL:

  ```text
  http://127.0.0.1:8765/
  ```

- The app is local-first, PDF-only, and Gmail draft-only.
- Manual Draft Handoff remains the safe fallback in every Gmail state.
- Optional Gmail Draft API OAuth is local-only. It may call only `users.drafts.create` after PDF preview, exact draft args, duplicate checks, and the Gmail handoff checklist are current.
- Gmail send, draft-send, trash/delete, and mailbox-search behavior are forbidden.

## What Is Implemented

- LegalPDF-style browser app shell and review drawer.
- Local PDF/photo upload, source evidence, OpenAI OCR evidence, automatic service-profile detection, numbered questions, duplicate/active-draft blocking, PDF preview, draft payload display, Manual Draft Handoff, optional guarded Gmail draft creation, Recent Work lifecycle controls, personal profiles, service profiles, reference editing, LegalPDF import preview/apply guards, public Git safety tooling, and Browser/IAB smoke coverage.
- Public repo safety boundary: `.gitignore` keeps real runtime overlays local, `.githooks/pre-commit` runs `python scripts/public_repo_gate.py --staged`, and the browser Public GitHub Readiness panel reports tracked Git safety separately from the stricter full-workspace privacy gate.
- Local Diagnostics now includes the read-only Python runtime doctor for checking interpreter/dependency drift before smoke or adapter work.
- LegalPDF adapter caller shim: `scripts/legalpdf_adapter_caller.py` now centralizes the safe endpoint list, read-only `/api/health` plus adapter-contract readiness probing, reusable HTTP JSON/multipart transport, caller-supplied sanitized source upload input, prepared-review request fields, stale-token helper, read-only/draft-only contract validation including the nested Gmail boundary and exact prepared-review binding fields, injected synthetic sequence used by the isolated adapter smoke, a guarded live-app CLI for isolated synthetic or caller-source runs, and secret-free readiness summaries.

## Validation Commands

Run from the root repo:

```powershell
python -m unittest discover tests
python scripts\runtime_doctor.py --json
node --check honorarios_app\static\app.js
node --check scripts\browser_iab_smoke.mjs
python scripts/public_repo_gate.py --hook-configured --json
python scripts\public_repo_gate.py --tracked --json
python scripts\local_app_smoke.py --base-url http://127.0.0.1:8765 --json
```

Optional sanitized candidate audit:

```powershell
python scripts\build_public_candidate.py --target output\public-candidate --json
python scripts\public_release_gate.py --root output\public-candidate --json
```

Optional isolated adapter caller CLI, after starting a disposable synthetic app runtime:

```powershell
python scripts\legalpdf_adapter_caller.py --base-url http://127.0.0.1:8765 --readiness-only --json
python scripts\legalpdf_adapter_caller.py --base-url http://127.0.0.1:8765 --allow-synthetic-recording --json
python scripts\legalpdf_adapter_caller.py --base-url http://127.0.0.1:8765 --source-file .\tmp\sanitized-legalpdf-source.pdf --source-kind notification_pdf --case-number 321/26.0CALLER --service-date 2026-05-06 --allow-synthetic-recording --json
```

## Public Release Workflow

1. Keep real local overlays ignored and untracked.
2. Stage files explicitly.
3. Run the tracked public repo gate:

   ```powershell
   python scripts/public_repo_gate.py --hook-configured --json
   python scripts\public_repo_gate.py --staged --json
   python scripts\public_repo_gate.py --tracked --json
   ```

4. Commit normally. The pre-commit hook reruns the staged gate.
5. Push to the public repo only when tests and the tracked gate pass.
6. Use `output/public-candidate` only when a separate sanitized export/audit tree is useful.

## Next Recommended Work

1. Keep hardening Browser/IAB smoke around real daily UI paths.
2. Keep growing the LegalPDF adapter caller shim toward the future real LegalPDF caller, keeping source upload, numbered answers, prepared-review token binding, and stale-token rejection executable only against isolated/synthetic state.
3. Continue testing real Gmail draft creation cautiously, keeping verification read-only and send actions forbidden.
4. Keep tightening `Next safe action` and duplicate/correction explanations if they confuse daily use.

## Private Data Rules

- Keep local private files ignored: `config/*.local.json`, `config/profile.json`, `config/profiles.local.json`, `config/*token*.json`, real `data/court-emails.json`, real `data/known-destinations.json`, real `data/service-profiles.json`, `data/gmail-draft-log.json`, `data/duplicate-index.json`, generated PDFs, source uploads, tokens, and logs.
- Do not publish root screenshots, generated files, real case numbers, court emails, personal profile/payment data, OAuth secrets, OpenAI keys, Gmail tokens, or Gmail draft IDs.
