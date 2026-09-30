# Photo intake defaults — 2026-09-30

Status: completed locally, applied and validated in the usual saved checkout; unpublished.

## Goal and authorized scope

The user clarified that a photo's capture day is the interpreting day by default, and the court in the capture city is the default payer. Implement those saved preferences, explain them honestly in review, and repeat source acceptance. Keep manual exceptions editable and ask when evidence/mapping is unavailable or ambiguous. No publication, Gmail operation or LegalPDF integration is authorized by this scope.

## Base and ownership

- Published base: main at `5b92d9f` (PR #60).
- Authoring: isolated `codex/fee-photo-defaults-20260930`; checks authored separately.
- Preserve the usual saved checkout's branch/history, all unrelated local edits and private records. Retain exact public-file and preference beforeimages before applying validated work.

## Contracts and implementation

1. Add an ignored, opt-in local photo preference file alongside the existing AI configuration. An absent preference file preserves existing source behavior.
2. Recover actual photo capture city separately from a service locality/police command. Select a single configured court/verified directory match, never fabricate an email.
3. Apply capture-day and city-court defaults only at photo intake; preserve original evidence and label selected values as user defaults. Later manual corrections remain authoritative. Unknown/ambiguous date or payer must remain unresolved and must not inherit a police header or unrelated default recipient.
4. Preserve routes, Gmail contracts, dependency versions, duplicate checks and safe browser rendering. The internal source-reading schema gains the capture-city evidence needed by the requested behavior.
5. Add synthetic regression cases; run focused checks and final Full. Review the browser flow and a rendered PDF, using fictional sources by default. The supplied real photo/PDF acceptance is a separately user-authorized bounded exception; keep its source/results in ignored local evidence. Replay the already-read real screenshot without another provider request where possible; if capture city requires the updated model extraction, use one bounded existing-connection source read.
6. Apply validated public files and explicitly authorized ignored preference changes to the saved checkout. Record exact outcomes in touched-scope guidance and this plan.

## Acceptance and risks

- Capture default uses the actual capture day for duplicates and PDF dates, including a different printed date, while manual exceptions remain effective.
- Photo-city default chooses the local court and its verified recipient; parent police district is not city evidence.
- Missing/ambiguous date, city or court mapping cannot yield false readiness through an AI police-header payer/default email.
- Source evidence visibly distinguishes policy defaults, OCR facts and private transport defaults.
- Existing behavior remains covered without opt-in; non-photo inputs stay unaffected.
- No real draft/index/record writes; private hashes and dependency pins remain unchanged except the newly authorized photo preference file.

## Progress

- Started from the merged quality baseline after an actual photo test exposed an unsupported police-header payer and the user clarified their intended default policy.
- Court mapping will use official public contact information checked on 2026-09-30, with public URLs recorded; it is a user-selected default rather than a legal determination of liability.
- Implemented separate capture-city extraction and opt-in photo defaults with visible provenance. Capture dates control duplicate/PDF dates; a configured capture-city court/contact replaces automatic profile/source routing coherently. Explicit profile choices and later manual corrections remain authoritative.
- Independent Astra review found additional precedence and edit-preservation cases. Repaired automatic source-court priority, preserved deliberately cleared date/recipient values through re-review, and cleared stale addresses/contacts/keys when the payer changes. Added meaningful offline regressions for those behaviors; focused quality passed 87 tests.
- An earlier integrated candidate Full passed 284 public synthetic tests and four isolated workflows. The initial Full run exposed a regression-test authoring error; it was corrected before the passing run. Subsequent close PDF inspection identified a bare service-location phrase needing shared grammar normalization; the bounded shared correction and its regression passed eight focused PDF tests. Dependency versions and application/API/Gmail contracts remain unchanged.
- One authorized actual source read of the supplied partial photo completed in 28.45 seconds with gpt-6.1-sol/high. The result used the saved date/city policy, with editable defaults and original evidence retained. Astra independently accepted the regenerated final PDF and reviewed the edge-case and grammar repairs. This was an explicitly user-authorized bounded real-source/PDF exception to ordinary fictional-source acceptance, with source/results kept in ignored local evidence. This bounded source check does not establish production accuracy.
- No Gmail operation, external publication or main-app integration was performed. Acceptance evidence, public-document beforeimages and private source/result artifacts remain local and ignored; public guidance includes no case/contact/personal values.
- Applied the latest public files and authorized ignored preferences to the usual saved checkout with exact beforeimages. Final saved-checkout Full passed 285 public synthetic tests and four isolated workflows. All 19 pre-existing private JSON files and the saved branch/head remain unchanged; launch preflight passed at 8878. Actual-source replay with saved settings was ready with zero additional provider calls.
- Latest browser acceptance passed deliberately cleared recipient/date values staying unresolved and a manual date exception remaining ready and visibly user-confirmed. Local implementation, application and required acceptance are complete. Publication and future main-app integration remain separately scoped.
