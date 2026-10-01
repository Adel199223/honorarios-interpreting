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

For notification handling, test issue-versus-interpreting appointment dates, written Portuguese dates, unrelated/cancelled appointments, mixed interpreting/translation scope and every case in a multi-case PDF. Verify the final PDF date and each email attachment, not only extraction. Test replacing a source with existing proof/custom email text. Within a batch, the same case/day with a blank and named period must block before files or records; distinct named periods remain valid.

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

Claim-option regressions are included in the intake/PDF/email groups and normal UI group. They cover truthful attendance-only wording, neither-claim rejection, shared-trip ownership and persisted draft guards; a synthetic pass still needs normal-screen and rendered-PDF acceptance.

Email-routing regressions belong to intake/email and normal UI groups. Exercise actual source recovery with ambiguous footer contacts, independent payer checks, exact-versus-broad aliases, same-value saved selection, normal select input/change events and delayed success/failure callbacks after switching prepared targets. Unit tests do not replace checking the chosen court email and exact PDF through ordinary browser controls.

Whole-app readiness regressions additionally cover nested EXIF capture dates, modification-only ambiguity, fragmented case suffixes, exact distance selection, immutable prepared filenames, tax profile values in actual PDFs, deliberate field clears and delayed uploads. Gmail tests must exercise timeout after remote creation, concurrent retries, partial local writes, restart discovery and recovery without a second create. These provider failures use offline fake transports. Local HTTP tests use a loopback base URL and reject foreign Host/Origin requests before any handler writes.

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

## Resume and backup recovery checks

`tests/test_workspace_draft.py` covers the editable browser snapshot, opaque per-runtime namespace, explicit resume, manual fields, per-case answers/evidence and shared-trip bindings. It checks missing/out-of-root files, explicit replacement profiles, stale responses, corrupt/quota-limited storage, Change source/Reset, the absent conditional home answer box, and the served dependency import-map version. The focused `ui` group runs these checks. Keep new static modules in both package/source-only copies and the versioned browser dependency graph.

Use ordinary browser controls to review a five-case source, move its travel owner, queue it, reload and resume. Confirm that all five rows return as needing review and that no previous PDF/email approval becomes actionable. Review again, refresh the queue, run batch preflight, prepare and inspect all five PDFs and the single email target. Repeat with manual fields entered before Build/Review. At a narrow viewport, check the resume banner and action remain above the reordered source panel. Exercise missing-file/profile repair in synthetic data; allow recovery of facts without silently accepting a different profile or missing attachment.

For backup changes, use isolated source and destination runtimes with fake Gmail transport. Export pending attempts, restore reviewed JSON/PDF/image recovery files, then complete local recording without another provider create. Verify old/legacy backup restore retains newer active/sent history and pending reservations, conflicts pause, incomplete recovery files remain blocked, and same-backup retry handles interruption. Check export/preview/restore warnings and the bounded file limits. Browser-local unfinished sessions and server-side attempt backups have separate storage and must not be reported as interchangeable. Current integrated test totals and actual browser evidence belong in the handoff/active plan, not inferred from this checklist.

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

For claim changes, exercise all three normal-screen choices, transfer/remove/restore a shared owner, corrected missing visit facts, immutable queue/prepared labels and stale edits. Inspect every resulting PDF and the narrower travel-only email. Same-city/day independent visits must remain separate; re-uploaded identical source bytes should retain the explicit group. Malformed recorded bindings must pause with an actionable message. The [completed claim acceptance](assistant/exec_plans/completed/2026-10-01_claim_options_shared_trip.md) records final 378-test/four-workflow candidate and saved checks, six corrected real documents and the fictional travel-only example; ordinary acceptance remains synthetic.

For email changes, select a saved contact through ordinary browser events, confirm a payer mismatch pauses, restore the correct contact and review again. In a mixed-city separate-PDF batch, choose every prepared case and check its recipient/body/single attachment. Switching must clear prior handoff/acknowledgement/IDs; delayed earlier success or failure must not affect the new target. Compare local RFC email attachment bytes with the reviewed PDF. The [completed email acceptance](assistant/exec_plans/completed/2026-10-01_email_routing.md) records 422-test/four-workflow candidate and saved checks, six actual-source cached handoffs, equal PDF text/pixels and six local email previews. It did not create actual Gmail drafts or contact providers.

## Subsequent bounded live acceptance — 2026-10-01

The [source-email plan](assistant/exec_plans/completed/2026-10-01_source_email_groups.md) covers later local grouping work. `test_source_email_groups.py` belongs to quick/intake/email/full. Its fictional checks cover source membership, all-child freshness, distinct PDF/history hashes, duplicate period matching, full superseded-group coverage, idempotence and retired/sent lifecycle protection. Normal browser acceptance must inspect five separate PDFs in one photo email and a separate second-photo email; rendered/PDF-byte checks complement synthetic fake-Gmail coverage. A local handoff or MIME preview is not an actual Gmail draft. See the plan for current candidate/saved validation and provider-versus-replay evidence.

The separately authorized [live acceptance plan](assistant/exec_plans/completed/2026-10-01_live_draft_acceptance.md) records six ordinary-UI draft creations, canonical local recording and six returned-ID UI verifications. Independent `users.drafts.get` reads with `format=raw` proved the exact recipient, subject, body and single own PDF bytes for those six drafts; all retained `DRAFT` and none had `SENT`. Metadata/ID verification alone does not establish body or attachment equality. This session made no new OpenAI source read or send; it is bounded evidence, not standing permission for future live tests.

The initial rejected OAuth refresh made zero Gmail create POSTs and returned no IDs. Its attempt and beforeimages were retained; the existing client/scope was renewed by the normal Google consent flow before a fresh guarded preparation. Preserve attempt-before-call journals and never blindly retry an uncertain create. A card must confirm creation only after a `created` response with a draft ID; blocked/error/info or missing-ID responses cannot claim success.

After the public wording regression was fixed and applied, candidate and saved-app Full each passed 423 synthetic tests plus four isolated workflows. Actual Gmail identities, content, credentials and proof receipts stay ignored and local. Publication requires the existing Windows hosted Full job on the final PR head; use the actual PR for current publication/merge state.


The first hosted [PR #61](https://github.com/Adel199223/honorarios-interpreting/pull/61) run revealed a test-only Node stdout decoding mismatch. All Node synthetic helpers now explicitly use UTF-8, and a Unicode round-trip test simulates a Windows `cp1252` default. Final candidate and saved-app Full each passed 424 tests and four isolated workflows. Retain the preceding 423-test candidate/saved checkpoint as historical live-acceptance evidence; require the corrected PR head to pass hosted Full. No application behavior, model, dependency or live Gmail operation changed.
