# Default phone Camera chooser

## Goal and scope

The user requested an actual original-photo import test and a Camera folder that opens by default, without navigating through Windows folders each time. Add a small local chooser rooted in an explicitly configured phone Camera folder. Keep ordinary file upload available for PDFs and other sources. This authorizes local setup, selected-photo import and implementation, not new provider calls, Gmail operations, publication or fee-history changes.

## Provenance and contracts

Continue in the attached `codex/photos-metadata-readiness-20261002` candidate from the completed local Photos/readiness scope (published local main base `a0ed383`). Preserve its uncommitted accepted work and the saved checkout's older overlays. Keep original bytes, existing metadata/review/duplicate/freshness rules, explicit Review source, and draft-only guards. Configured folder paths and photo evidence remain ignored and private.

## Implementation and acceptance

1. Read-only bounded folder listing and one selected-file read; reject traversal, symlinks, changed/oversized/unsupported files and disconnected phone access.
2. In-app chooser defaults to Camera only when configured. Browsing/cancelling preserves current work. Choosing a replacement invalidates prepared state; stale asynchronous responses cannot overwrite later work. Other files use the existing native picker.
3. Run focused synthetic backend/UI tests, then locked Full validation on the integrated candidate. Apply only touched verified files to saved app with exact beforeimages, verify saved checks, restart owned server, and test the actual original through visible controls with AI off.
4. Verify all previous config/data hashes remain unchanged except the new explicit local source-folder preference. Preserve unfinished browser work and stop before PDF/Gmail creation. Record UI evidence and limitations honestly.

## Risks and rollback

The phone may disconnect or return online placeholders slowly. Do not scan recursively, bulk-download photos, infer city, read unrelated folders or rewrite originals. Bound listing, names, sizes and selected reads; keep errors actionable. The fixed folder is configured outside the browser and never accepted from an HTTP request. Existing local Host/Origin checks remain mandatory. Beforeimages are stored in ignored task evidence for both checkouts; rollback only this task's touched files and newly introduced preference.

## Progress — 2026-10-02

- Existing native file input has no fixed-directory option. The browser chooser selected the known original path; native folder navigation/default memory has not been established by that API action.
- Added task beforeimages and protected JSON baseline. Implementation in progress; no completion claimed.

- Implemented fixed-root Camera status/list/file endpoints, in-app default chooser with search/paging and native fallback, staged-file freshness checks, and safe resume/manual transitions. Listing reads metadata only; selected bytes enter the existing source-upload flow.
- Normal isolated browser checks passed opening/reopening Camera, date filtering, staged selection then explicit Review source, native fallback review and disconnected-folder guidance. No provider calls occurred.
- Initial Full found an outdated test-group membership expectation and UI mocks copied before the final staged-source helper; corrected these harness issues. Cross-layer review additionally found old-intake batch/review and resume/manual selection lifetime gaps; guarded those paths before final validation. Initial failed output remains in ignored evidence.

## Completed local acceptance — 2026-10-02

- Candidate and saved app each passed locked Full validation: **770 public synthetic tests and four isolated workflows**, including installed-wheel/environment, documentation and JavaScript checks. Final logs are retained privately alongside the earlier failed harness checkpoint.
- The actual saved browser opened Phone Camera directly from Add source file, selected an original phone JPEG, then used the ordinary explicit Review source action with AI off. Filename, original hash, capture date and GPS remained visible after review. This live test exposed and fixed the single-source evidence panel being replaced by Manual review; a regression now covers metadata/preview retention.
- Synthetic browser acceptance covered reopen/cancel, date search, selected-file review, the native other-file fallback, disconnected-folder guidance and staged-selection/manual transitions. Focused tests cover file-root/type/size/fingerprint/race checks, stale asynchronous results and old-intake review/prepare/batch gates.
- Applied 19 touched public code/test/guidance files with exact beforeimages and matching candidate/saved hashes. All 24 previous protected config/data JSON hashes are unchanged. The only new private configuration is the explicitly requested original Camera folder preference. Browser unfinished work was preserved; the current Camera dialog is ready for the user.
- No provider call, new fee PDF, Gmail operation, history write, dependency change, publication or LegalPDF integration occurred. The live source review saved only its normal local evidence. Owned isolated test resources are closed; the usual app remains running.
- Limits: phone connectivity is required; the chooser supports JPEG/PNG originals, not HEIC/HEIF. GPS is preserved but does not automatically resolve a city. Unknown city evidence still requires an ordinary review answer. The native browser picker has no guaranteed fixed-folder default; the configured in-app chooser supplies that behavior.

The authorized task is complete locally. Future work starts from a fresh request; earlier provider/history operations remain consumed. Private evidence, screenshot, updated simple setup guide and validation receipts are retained under ignored task directories.
