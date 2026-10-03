# Retain warnings after removing drafts

## Goal and scope

The user authorizes future draft removal to preserve case/date/period duplicate warnings automatically. Add a local Recent Work removal action, retain accurate lifecycle independently of duplicate protection, and explain missing Gmail drafts through the existing read-only sync. No actual email send/delete/create, new source read, history migration, publication or shutdown is part of this work.

## Baseline and contracts

Continue the attached Camera-through-May candidate based on PR 64, preserving its accepted local overlays and the saved app. The prior 1,086-test/four-workflow acceptance remains historical. Duplicate-index remains the shared warning source; sent evidence, grouped identities, periods, intentional correction coverage, review freshness and draft-only boundaries remain authoritative. Earlier retired records are not reclassified without an explicit new transition.

## Implementation and acceptance

1. Keep historical drafted protection when a new removal/archive/missing transition retires a draft. Record the real lifecycle separately and update the index before the draft log.
2. Offer a local **Remove from Drafted — keep warning** action. Removed records remain auditable and do not claim to have been sent or deleted from Gmail.
3. Report confirmed missing Gmail drafts separately from API errors; retain protection and never infer sending from disappearance.
4. Test single/grouped/period requests, stale payloads, partial writes, correction/replacement, backup restore and all creation boundaries in isolated runtimes.
5. Run normal browser acceptance, final Full validation and exact-file saved-app application with protected-state hashes.

## Rollback and progress

Exact beforeimages and acceptance receipts are retained under ignored `tmp/retained-draft-warning-2026-10-03/`. Apply only reviewed changed files to the saved app after validation; preserve all existing local files and private records. Revert only this scope from its beforeimages if acceptance fails.

- 2026-10-03: Confirmed Gmail disappearance already preserves ordinary drafted history, but explicit `not_found`/`trashed` retirement removes protection. Implementation started in the existing candidate.

- Final acceptance: 1,110 public tests, four isolated workflows and JavaScript syntax checks passed. Independent review found no actionable defects. Normal-browser tests exercised the in-page confirmation, cancellation, archive, removal from Drafted, and same-case/date retry warning. Gmail/provider calls were forbidden in the synthetic fixtures.
- The in-page confirmation defaults to Cancel and preserves stale-workspace/history guards. It replaces the archive action's native confirmation so the ordinary browser flow is accessible and testable. No real draft was removed during acceptance.
- Completion is local: exact accepted files are applied to the usual saved app with beforeimages and hash verification, followed by an ownership-checked restart and read-only browser verification. The private apply receipt records final status; prior accepted overlays and protected history remain intact. No publication, history migration, real Gmail mutation or shutdown is included.
