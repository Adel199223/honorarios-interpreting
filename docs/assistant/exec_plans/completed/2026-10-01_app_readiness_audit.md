# Whole-app readiness audit

## Goal and authorized scope

The user requested a thorough review of the fee app before trying it personally. Audit the complete workflow, reproduce significant defects, implement bounded verified corrections, and validate the result through public synthetic tests, ordinary browser controls and rendered PDFs. This work uses the existing product and locked dependencies. Publication, further live Gmail/provider operations and main-app integration are separate.

## Starting point and provenance

- Published base: `668abdb2d63a163f9e6fccff8fe3d33e1faf341c`, merged PR #62. Its final PR and merged-main Windows Full checks passed.
- Candidate: `codex/fee-app-readiness-audit-20261001` in the retained isolated review checkout.
- The saved application has existing local work and private overlays. Preserve its branch/history, settings, records and accepted documents. Apply only validated touched public files after retaining exact beforeimages.
- Independent domain, state/email and browser-code reviews complement root's actual browser/PDF audit. Each implementation worker must use its own worktree.

## Contracts to preserve

- Photo capture day/city preferences, named service venues and manual exceptions.
- Separate case identities/PDFs, one shared trip per declared visit, three claim choices and one email per photo.
- Public routes and existing payload compatibility, reviewed immutable artifacts, all-child duplicate/correction protection and safe text rendering.
- Draft-only email operations, explicit review acknowledgement, private local records and existing dependency/model configuration.

## Work and acceptance

1. Map the application and review code, tests, configuration boundaries, launch behavior and normal screens.
2. Reproduce significant failures with fictional inputs in isolated runtimes; record confirmed findings and distinguish optional improvements.
3. Correct confirmed issues in bounded changes with meaningful regression tests. Independently review the integrated fixes.
4. Exercise ordinary browser source/manual intake, multiple cases, claim choices, editing, questions, queue, PDF preview, grouped/separate email and synthetic Gmail outcomes. Inspect generated PDF pages and exact payload identities. Test interruption/retry behavior where affected.
5. Run focused checks during development and Full on the final integrated candidate. Synchronize touched documentation and verify privacy gates.
6. Apply accepted public changes to the saved app with beforeimages, verify protected state unchanged, and report readiness and remaining limitations plainly.

## Risks and recovery

Case identity, dates, recipient, travel and draft lifecycle bugs can create incorrect requests. Never test record-writing/provider paths against private runtime data. Use explicitly synthetic runtime directories and fake transports. Preserve exact original public files before applying fixes; retain reproducible evidence locally. Do not infer production OCR accuracy or a new live Gmail acceptance from synthetic checks.

## Progress

- 2026-10-01: Read current architecture, operating rules and prior acceptance; started three independent reviews and a fresh browser audit. Initial suspected boundaries are under synthetic reproduction; no production settings or records changed.
- Confirmed and corrected photo capture-versus-modification date handling, fragmented case suffixes, ambiguous distance matching and prepared-artifact overwrites. Actual PDF regressions exercise the wrong-date/distance and repeated-preparation failures.
- Confirmed and corrected late attachment/manual responses, duplicate source reads, obsolete upload errors, deliberate field clears and missing manual-profile fallback. A suspected case-switch review race was disproved and excluded.
- Confirmed incorrect tax fallback and unsupported AI-only email promotion. Gmail timeout and partial local-record failure reproduced duplicate remote creation; durable attempts and local-only recovery are under integration and independent adverse-path review.
- Restricted local HTTP Hosts and unsafe cross-origin browser requests; ordinary loopback callers and OAuth callbacks remain compatible. Six boundary tests and 91 focused tests passed in the isolated authoring checkout.
- Root's ordinary synthetic browser controls completed manual entry, rendered PDF review and fake-Gmail creation/verification. Five-case source replay then verified capture-day defaults, explicit date clearing/confirmation, case switching, moving the single travel owner and bulk queueing. These are offline workflow tests, not new OCR or live-Gmail acceptance.
- Independent review reproduced recovery discovery after reload and uncertain correction reconciliation gaps; their fixes are being integrated before final acceptance.
- Final independent recovery review corrected and rechecked restart discovery, uncertain replacement resolution and cross-workspace ID isolation. An actual browser recovery then exposed misleading verification wording; the result now accurately describes local recording and retains original creation evidence separately.
- A verified interrupted-profile-write failure was fixed with atomic replacement and fail-closed loading of malformed existing stores. Legacy absent-file migration remains supported. Focused profile consumer checks passed 127 tests and 207 subtests.
- Final combined candidate and saved-app Full each passed **529 public synthetic tests and four isolated workflow checks**. Earlier Full runs exposed an installed-wheel test Host mismatch, then a prematurely started run with unresolved test-harness merge markers; both were corrected and complete validation rerun. The earlier integrated 528-test checkpoint also passed before the final recovery-copy regression was added. Locked dependencies/models were preserved.
- Root's final ordinary browser acceptance covered source upload/review, cleared-date question and confirmation, moving the sole shared-trip claim, five-case queue/preflight, five distinct PDFs in one email, fake creation interrupted before local recording, actual server restart, Recent Work discovery, local-only recovery and fake verification. All five rendered pages were inspected; repeat preparation retained earlier versions with matching text. A second synthetic runtime verified partial-history recovery and uncertain no-draft resolution. The IAB native confirmation stalled automation; the user accepted it and the resulting local resolution was verified. No live provider/Gmail call occurred.
- Validated public files are applied to the saved app with exact beforeimages. All **84 protected configuration/history/document entries**, saved branch and saved commit are unchanged. Local synthetic screenshots, reproduction scripts, Full logs and application receipts remain ignored. No private records/documents were uploaded, no new real drafts were created, and no email was sent.

## Completion and remaining limits

The bounded audit and significant corrections are complete locally and ready for the user's own trial. This audit is based on published main `668abdb` after PR #62 merged; these newer corrections are **unpublished**. Publication, live provider acceptance and main-app integration require their own scope.

No remaining concrete blocker was found within the exercised scope. The workflow checks do not establish universal OCR accuracy. GPS-only capture-city lookup, mixed written-translation/interpreting acceptance, broader UI simplification and safe journal-inclusive machine-move backup remain separate improvements. Current backup export does not include the new attempt journal; existing restore preserves it. Preserve that private journal separately when moving machines, and never discard uncertainty to bypass duplicate protection.
