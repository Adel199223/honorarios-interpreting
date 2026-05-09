# Public Release Checklist

The root workspace is the live public Git repository. Sensitive runtime data remains local and ignored; public updates are safe only when tracked Git content passes the repo gate.

## Tracked Git Gate

- Stage files explicitly; do not rely on broad staging when private overlays exist.
- Run the staged gate before committing:
  `python scripts/public_repo_gate.py --staged --json`
- Run the tracked gate before pushing:
  `python scripts/public_repo_gate.py --tracked --json`
- Confirm `.githooks/pre-commit` is active with:
  `git config --get core.hooksPath`
- Confirm `git ls-files` contains no blocked runtime paths such as real local configs, draft logs, duplicate indexes, generated artifacts, real court/email directories, or source uploads.
- Confirm the gate reports no IBANs, personal names/addresses, real `@tribunais.org.pt` emails, OpenAI keys, Google OAuth secrets, Gmail tokens, Gmail draft IDs, or local-machine paths.

## Runtime Overlay Rules

- Keep real `config/profile.json`, `config/profiles.local.json`, `config/email.json`, `config/*.local.json`, and `config/*token*.json` ignored.
- Keep real `data/gmail-draft-log.json`, `data/duplicate-index.json`, `data/profile-change-log.json`, `data/court-emails.json`, `data/known-destinations.json`, `data/service-profiles.json`, and `data/precedents.json` ignored.
- Keep `output/`, `tmp/`, `.playwright-mcp/`, root-level screenshots, generated PDFs, source uploads, and draft payloads ignored.
- Track sanitized `.example.json` fixtures and synthetic tests instead of real operational data.

## Verification

- Confirm `python -m unittest discover tests` passes from the root repo.
- Confirm `node --check honorarios_app\static\app.js` passes.
- Confirm `node --check scripts\browser_iab_smoke.mjs` passes.
- Confirm the browser app starts with `python -m honorarios_app.web --host 127.0.0.1 --port 8765`.
- With the app running, confirm `python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --json` returns `status: ready`.
- In the browser app, open References -> Public GitHub Readiness and confirm the tracked Git gate is ready. The full-workspace privacy gate may remain blocked when ignored private overlays exist locally.
- In the browser app, open References -> Local Diagnostics and confirm the safe smoke commands are visible and copyable. This panel must remain read-only and must not contact real Gmail.

## Optional Sanitized Candidate Audit

- Build a sanitized candidate when you want a separate export/audit tree:
  `python scripts/build_public_candidate.py --target output/public-candidate --json`
- Run the full-tree privacy gate on that exact candidate:
  `python scripts/public_release_gate.py --root output/public-candidate --json`
- Require `public_ready: true` for the candidate tree before sharing it as an artifact.
- The candidate uses synthetic profile, email, court, destination, service-profile, intake, and smoke-test fixtures. Review it before using it for any separate publication workflow.

## Publishing Rule

Publish from the root public repo only after tests and the tracked Git gate pass. Use `output/public-candidate` for sanitized audits or exports, not as the normal source of truth.
