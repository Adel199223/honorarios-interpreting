# Next Thread Handoff

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
- LegalPDF adapter caller shim: `scripts/legalpdf_adapter_caller.py` now centralizes the safe endpoint list, read-only `/api/health` plus adapter-contract readiness probing, reusable HTTP JSON/multipart transport, caller-supplied sanitized source upload input, prepared-review request fields, stale-token helper, read-only/draft-only contract validation including the nested Gmail boundary and exact prepared-review binding fields, injected synthetic sequence used by the isolated adapter smoke, a guarded live-app CLI for isolated synthetic or caller-source runs, and secret-free readiness summaries.

## Validation Commands

Run from the root repo:

```powershell
python -m unittest discover tests
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
4. Improve UX explanations for `Suggested Next Step` and duplicate/correction states if they confuse daily use.

## Private Data Rules

- Keep local private files ignored: `config/*.local.json`, `config/profile.json`, `config/profiles.local.json`, `config/*token*.json`, real `data/court-emails.json`, real `data/known-destinations.json`, real `data/service-profiles.json`, `data/gmail-draft-log.json`, `data/duplicate-index.json`, generated PDFs, source uploads, tokens, and logs.
- Do not publish root screenshots, generated files, real case numbers, court emails, personal profile/payment data, OAuth secrets, OpenAI keys, Gmail tokens, or Gmail draft IDs.
