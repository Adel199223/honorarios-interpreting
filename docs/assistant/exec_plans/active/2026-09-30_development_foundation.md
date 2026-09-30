# Fee app development foundation

## Goal and scope

Execute the user's approved priorities: recover the saved beginner interface on the published setup; verify upload -> review -> numbered answers -> PDF preview -> manual email handoff in an actual browser; add safe, selectable test groups and public synthetic business-rule regressions; add focused development guidance and a user guide; extract useful code responsibilities without changing contracts. No additional plugin or version change is justified by the assessment.

Main-app integration, private data import, live providers/Gmail, dependency upgrades, destructive operations and new publication are outside this implementation scope. Publication of the earlier preparation in PR #58 is historical authorization for that completed scope, not this update.

## Provenance

- Fee repository: existing Honorários checkout; primary saved branch `codex/beginner-guided-intake-ux` is preserved.
- Authoring worktree: `.worktrees/development-foundation`.
- Branch: `codex/fee-development-foundation-20260930`.
- Approved base: `origin/main`, `bb9b1cf556ba07bcb43cea39ae9defed1090d20e` (PR #58).
- Saved interface source: exact original fifteen-file patch from local preparation beforeimages, applied cleanly by context onto the approved base.
- Target: verified local development build; `main` remains the published integration branch. This branch is noncanonical until a separately approved publication.
- Parallel coding uses separate worktrees with local checkpoint commits; inspect/transplant their bounded scopes into this authoring branch.

## Contracts

Preserve route IDs/paths, payload shapes, submitted values, adapter contract version, date/duplicate/recipient checks, review-freshness binding, safe text rendering, Gmail draft-only boundaries, historical server defaults and dependency lock. Synthetic browser/API checks must use disposable runtime roots and strip provider credentials. Never operate private live services during acceptance.

## Implementation order

1. Recover and checkpoint the saved interface, then reconstruct the locked environment. Preserve original work and local/private files.
2. Launch an isolated synthetic app, verify the complete beginner journey using current browser tooling, inspect the generated PDF, and repair concrete workflow issues.
3. Add named fast test groups plus full selection, keeping source-only temporary test execution and an explicit public manifest. Add fictional intake/PDF/draft rule tests, and split the broad public test file along clear responsibilities where useful.
4. Extract a bounded backend responsibility from the large services module and a bounded browser responsibility when useful. Preserve outward contracts and test the extracted behavior.
5. Add a small plan lifecycle guide, acceptance checklist, concise user guide, and coherent routing/handoff/architecture/validation guidance. Record actual evidence and deferred production integration.
6. Run focused checks during changes; run final Full, publication-content checks, browser acceptance and preservation checks on the final build. Apply verified updates to the saved development checkout only after preserving exact beforeimages; retain its private runtime and earlier branch/history.

## Acceptance matrix

| Requirement | Proof |
| --- | --- |
| Saved beginner UI combined with published setup | Base lineage plus scoped recovered patch and preservation hashes |
| Beginner journey works | Actual browser interactions, visible state and rendered synthetic PDF, current served build identity |
| Fast groups and full checks | Selection tests proving each group membership, zero unsafe/unlisted imports, passing group runs and final Full |
| Business rules covered publicly | Fictional positive/negative date, duplicate, request, PDF and recipient/draft tests |
| Useful modernization | Clear extracted responsibilities, unchanged outward contract and regression checks |
| Harness/user guidance | Local links/routing validation, tested documented commands and clear current handoff |
| Saved app ready to develop | Applied-file/preservation evidence, pinned environment preflight, final validation, launch instructions |

## Rollout and fallback

Use isolated checkpoints and exact local beforeimages. Do not rewrite the original branch or delete retained environments/worktrees. If a browser capability is absent, keep the failure evidence and use another supported browser surface with isolated data; do not substitute API-only proof for browser acceptance. Failed checks must remain recorded. The implementation remains unpublished unless the user separately authorizes its release.

## Risks and assumptions

- Saved work changes photo-date/AI evidence as well as visual layout; inspect behavior, not only appearance.
- Private historical tests may contain real fixtures. Add public synthetic regressions instead of indiscriminately including those files.
- Large files can have implicit coupling. Prefer bounded, behavior-preserving extraction and verify current contracts.
- Every browser write is local synthetic; network/provider calls are forbidden in these checks.

## Progress and evidence

- 2026-09-30: current goal and authorization inspected. Approved base verified; original patch applied cleanly. Fresh locked environment reconstructed with unchanged versions. Original saved checkout remains untouched by recovery.

- 2026-09-30: recovered interface checkpoint `7a4d066` is combined with the locked baseline. Pure browser review guidance and source-evidence responsibilities were extracted; existing outward exports/routes remain available.
- Actual synthetic browser acceptance: a complete PDF source reached review, generated PDF preview, and the manual handoff; a missing-date PDF required a visible numbered answer before the same sequence. The rendered fictional PDF was manually inspected for wording, dates, layout and clipping. Changing source cleared the prepared client controls. No providers or Gmail were called.
- Browser acceptance found and repaired an unavailable automatic profile selection. Further observed issues are being repaired before final acceptance: stale home guidance after preparation, weak fallback visibility, awaited-response invalidation, and EXIF capture dates bypassing the existing confirmation requirement.
- Focused worker validation passed all named groups and Full (153 public synthetic tests plus four isolated smokes); this is preliminary worker evidence, not the final root/application acceptance. Its bounded implementation was integrated in checkpoint `9b4de2f`.
- Failed attempts retained: initial browser binding timeout recovered through the same supported tool; a preview locator deadline expired while generation was in progress, then fresh visible state confirmed the completed preview. AX summary controls required their actual accessibility targets rather than guessed DOM roles. These tooling observations do not establish app failures.
