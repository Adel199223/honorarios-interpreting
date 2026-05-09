# Next Thread Handoff

Current date: 2026-05-09

## Project State

- Private working folder: `%USERPROFILE%/example-path`
- Publishable Git repo: `output/public-candidate`
- Public remote: `https://github.com/Adel199223/honorarios-interpreting`
- Public branch: `main`
- The private working folder is intentionally not a Git repository because it contains local runtime data, generated documents, draft logs, and private configuration.
- Publish only from the sanitized public candidate after its privacy gate passes.

## App Status

- Local app command:

  ```powershell
  python -m honorarios_app.web --host 127.0.0.1 --port 8766
  ```

- Browser URL:

  ```text
  http://127.0.0.1:8766/
  ```

- The app is local-first, PDF-only, and Gmail draft-only.
- Manual Draft Handoff remains the safe fallback in every Gmail state.
- Optional Gmail Draft API OAuth is local-only. It may call only `users.drafts.create` after PDF preview, exact draft args, duplicate checks, and the Gmail handoff checklist are current.
- Gmail send, draft-send, trash/delete, and mailbox-search behavior are forbidden.

## What Is Implemented

- LegalPDF-style browser app shell and review drawer.
- Local PDF/photo upload, source evidence, OpenAI OCR evidence, automatic service-profile detection, numbered questions, duplicate/active-draft blocking, PDF preview, draft payload display, Manual Draft Handoff, optional guarded Gmail draft creation, Recent Work lifecycle controls, personal profiles, service profiles, reference editing, LegalPDF import preview/apply guards, public-candidate privacy tooling, and Browser/IAB smoke coverage.

## Validation Commands

Run from the private working folder:

```powershell
python -m unittest discover tests
node --check honorarios_app\static\app.js
node --check scripts\browser_iab_smoke.mjs
python scripts\local_app_smoke.py --base-url http://127.0.0.1:8766 --json
python scripts\public_release_gate.py --root output\public-candidate --json
```

Run from `output/public-candidate`:

```powershell
python -m unittest discover tests
git diff --check
git status -sb
git rev-list --left-right --count origin/main...HEAD
```

## Public Release Workflow

1. Rebuild the candidate:

   ```powershell
   python scripts\build_public_candidate.py --target output\public-candidate --json
   ```

2. Run the privacy gate against the exact candidate:

   ```powershell
   python scripts\public_release_gate.py --root output\public-candidate --json
   ```

3. Commit and push only from `output/public-candidate`.

## Next Recommended Work

1. Keep hardening Browser/IAB smoke around real daily UI paths.
2. Use the LegalPDF adapter contract to design a future caller shim, without writing to LegalPDF Translate yet.
3. Continue testing real Gmail draft creation cautiously, keeping verification read-only and send actions forbidden.
4. Improve UX explanations for `Suggested Next Step` and duplicate/correction states if they confuse daily use.

## Private Data Rules

- Keep local private files ignored: `config/*.local.json`, `config/profile.json`, `config/profiles.local.json`, `data/gmail-draft-log.json`, `data/duplicate-index.json`, generated PDFs, source uploads, tokens, and logs.
- Do not publish root screenshots, generated files, real case numbers, court emails, personal profile/payment data, OAuth secrets, OpenAI keys, Gmail tokens, or Gmail draft IDs.
