# Readiness publication and cleanup — 2026-10-01

## User-authorized scope

The user explicitly requested PR, merge and cleanup after accepting the completed app review and three actual draft creations. Publish the cumulative reviewed improvements from `codex/fee-three-source-audit-20261001` to `main`, wait for the hosted Windows Full check on the exact PR head, merge when green, update the clean main checkout and safely retire finished work. Keep private settings, documents, credentials, Gmail state and unfinished work local and unchanged. This operation does not repeat source reads or Gmail actions.

## Provenance and acceptance

- Published base: `668abdb2d63a163f9e6fccff8fe3d33e1faf341c`.
- Accepted local checkpoint before publication guidance: `178d91ac40634129ea41f82a717128b596d93e80`.
- Cumulative scope: source/PDF decision accuracy, local unfinished-work resume, recoverable Gmail attempts and backup restoration, profile/UI correctness and associated tests/guidance.
- Candidate and saved application previously passed 615 public tests and four isolated workflows. Three fresh actual source-to-Gmail runs passed rendered-PDF inspection and 120 independent draft-content/unsent checks. These consumed operations are historical acceptance and must not be replayed.
- Independent pre-publication privacy review covers all outgoing commit trees/messages and the final tracked tree, including removed historical blobs. Private documents/settings/identities remain ignored.

## Publication and cleanup contract

1. Confirm the published base is an ancestor; preserve the primary saved app branch and overlays.
2. Run final Full and public tracked/hook/staged gates. Create one PR for the accepted cumulative branch.
3. Bind hosted Windows Full success to its exact head SHA; confirm no unresolved review blocker and use an expected-head merge.
4. Fast-forward the clean main checkout. Match merged application code to the accepted saved app.
5. Before removing a finished worktree, verify clean status and ancestry or patch equivalence; retain needed ignored evidence and local archive references with hashes. Preserve unfinished worktrees and any still-referenced artifact paths.
6. Retire the published remote branch, prune stale references and recheck protected saved state. No force-push or main history rewrite.
7. Record actual PR, hosted checks, merged SHA, applied identity and cleanup outcomes in the ignored publication receipt. Actual GitHub/receipt state governs final merge status; this preparation record must not be mistaken for a completed remote merge.

## Local publication preparation completed

Final local Full passed 615 public tests and all four isolated workflows. Independent review passed all 35 outgoing commit trees/messages, 283 file versions and 142 then-tracked final files, with no privacy or significant code blocker. Current guidance adds only public-safe publication state and is covered by staged/tracked gates. No product code changed after accepted live testing.

This preparation is decision-complete: publish the reviewed branch, require exact-head hosted success, merge and execute the bounded cleanup contract. Seven harvested worktrees may be retired after preserving their ignored evidence and recovery references; five dirty older worktrees and unmatched historical branches remain preserved. Keep the saved app and clean main checkout; preserve any worktree still referenced by existing artifacts.

The actual PR, hosted result, merge SHA and cleanup receipt establish remote completion. Do not infer that the merge has happened from this pre-merge plan. Completed source/Gmail operations remain consumed and must not be repeated during publication.
