# Public Release Checklist

Create a public GitHub repo only after this checklist is complete.

## Privacy Gate

- Build a sanitized publish candidate first:
  `python scripts/build_public_candidate.py --target output/public-candidate --json`
- Run `python scripts/public_release_gate.py --json` on the exact candidate tree and require `public_ready: true`.
- In the browser app, use References -> Public GitHub Readiness to run the current-workspace gate and Build sanitized candidate to create a candidate tree.
- Remove or ignore real `config/profile.json`.
- Remove or ignore real `config/email.json`.
- Remove or ignore `data/gmail-draft-log.json`, `data/duplicate-index.json`, and `data/precedents.json`.
- Remove or ignore all `output/` and `tmp/` artifacts.
- Remove root-level browser QA screenshots before publishing.
- Replace real examples with synthetic case numbers, fake Gmail IDs, fake PDFs, and fake profile/payment details.
- Confirm the scan has no IBANs, personal names/addresses, real `@tribunais.org.pt` emails, OpenAI keys, Google OAuth secrets, Gmail draft IDs, or real case history.

## Repository Gate

- Add a license before public publishing.
- Keep `.env` and local overlays ignored.
- Confirm `python -m unittest discover tests` passes from a clean clone.
- Confirm the generated public smoke suite covers the LegalPDF-style workflow landmarks, draft-only reference status, secret-free Google Photos status, read-only LegalPDF integration preview/report/checklist/import-plan/apply-history/apply-detail/apply-restore-plan APIs, guarded LegalPDF restore-control copy, confirmation-blocked LegalPDF apply and restore behavior, injected browser click-through smoke, injected optional interaction smoke, and the privacy gate.
- Confirm the browser app starts with `python -m honorarios_app.web --host 127.0.0.1 --port 8765`.
- With the app running, confirm `python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --json` returns `status: ready`.
- In the browser app, open References -> Local Diagnostics and confirm the default live smoke, source-upload smoke, and supporting-attachment smoke commands are visible and copyable. This panel must remain read-only and Gmail-free.
- Confirm `python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --source-upload-checks --json` returns `status: ready`; this API-only path verifies synthetic photo/PDF Source Evidence and Review Attention without browser tooling, PDF preparation, draft recording, or Gmail calls.
- Confirm `python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --supporting-attachment-checks --json` returns `status: ready`; this API-only path verifies synthetic declaration/proof upload evidence without preparing PDFs, creating draft payloads, recording drafts, or calling Gmail.
- If optional browser tooling is installed, confirm `python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --json` returns `status: ready`; this default browser path may run the non-writing batch preflight, but it does not prepare PDFs or record drafts.
- In Codex, confirm the Browser/IAB Node REPL runner can import `scripts/browser_iab_smoke.mjs` and returns `status: ready` for the default review/batch path plus `answerQuestions: true` for the numbered-answer loop and `applyHistory: true` when checking LegalPDF Apply History/Detail/Restore Plan and guarded restore controls. The shell command `--browser-iab-click-through --browser-answer-questions --browser-apply-history` should fail fast with a `node_repl_cell` handoff instead of hanging.
- If optional browser tooling is installed, confirm `python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --browser-click-through --browser-upload-photo --browser-upload-pdf --browser-correction-mode --json` returns `status: ready`; this browser UI path uses disposable synthetic uploads, may store synthetic source-preview artifacts, and still blocks prepare, record, and draft-status writes.
- For disposable/synthetic state only, confirm `python scripts/local_app_smoke.py --base-url http://127.0.0.1:8765 --interaction-checks --json` returns `status: ready`; this opt-in mode can write local PDF/payload artifacts but still never calls Gmail.
- Confirm CI uses only synthetic fixtures.

## Publishing Rule

Publish from the clean sanitized candidate repo, not directly from the current working directory that contains real operational data. Keep the current workspace private even when the candidate passes.
