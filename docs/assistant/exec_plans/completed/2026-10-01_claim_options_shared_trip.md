# Claim choices and shared trips — 2026-10-01

## Goal and authorized scope

Correct the user's existing six local requests: the five cases at the same location belong to one visit, so only one request claims that trip. Add simple interpreting-and-travel (default), interpreting-only and travel-only choices, including truthful attendance wording when no interpreting work happened. Implement, test through ordinary browser controls, render and independently inspect the replacement PDFs, apply validated files to the saved app and synchronize touched guidance. The first case in the multi-case photo carries the shared-trip claim unless changed by the user. No Gmail, record/index writes, publication, new provider calls or main-app integration.

## Baseline and ownership

- Local accepted base: `70d92f8`, the completed six-case-photo work. Published main remains `5b92d9f` through PR #60.
- Root authoring: isolated `codex/fee-claim-options-20261001`; separate domain/UI worktrees own disjoint implementation files. Keep the saved checkout's branch/history and unrelated changes intact.
- Preserve exact beforeimages and hashes of existing private files, previous result PDFs and touched guidance. Reuse the two captured provider responses in isolated runtimes; do not contact the provider again.
- Optional `claim_interpreting` defaults true; existing `claim_transport` stays compatible. Optional explicit `travel_group_id` binds a shared visit; group membership must not be inferred globally from city/date.

## Steps and acceptance

1. Implement three claim choices in shared domain/PDF rules. Neither claim selected is unresolved and cannot generate. Interpreting-only does not require transport data. Travel-only requests transport for attendance without asserting performed interpreting or inheriting unsupported service-specific IVA/IRS wording. Keep existing personal/payment/signature facts and honor explicit custom text by pausing conflicting wording rather than rewriting it silently.
2. Add a prominent per-request choice and clear multi-case shared-trip controls. Default an eligible reviewed source cohort to one trip, with a selectable owner. Separate trips and no travel remain explicit choices. Preserve case-specific corrections; moving travel must not invent interpreting on a travel-only row. Every changed request needs fresh review and stale prepared/preflight state is invalidated.
3. Validate explicitly marked groups in browser services and direct CLI before artifact writes: consistent visit date, physical venue/destination and selected personal profile; at most one travel claimant. Preserve duplicate identity as case/date/period, so claim choices cannot bypass existing records.
4. Cover meaningful fictional regressions and rendered PDFs for each mode, group reassignment, malformed/conflicting groups, no-artifact failures and stale state. Run final Full in the assembled candidate and saved checkout. Preserve dependency pins.
5. Use ordinary browser controls with captured source-reader results to regenerate all six real PDFs; one of the five same-visit cases claims transport and four claim interpreting only. Inspect every rendered page and have an independent fact/wording review. Exercise a fictional travel-only request through the normal screens, without provider/Gmail calls.
6. Apply validated public files through baseline/history/hash guards with beforeimages. Preserve private config and draft/index records. Save replacements in a new ignored results directory and mark the earlier local review index superseded, preserving its beforeimage and PDFs. Update only touched docs and move the plan to completed after required acceptance.

## Evidence limits and continuity

This work represents the user's requested claim content, not new statutory fee/tax advice or an assurance of court acceptance. Omit unsupported service tax wording for travel-only instead of inventing reimbursement tax treatment. New actual requests remain subject to the user's PDF review before sending. Shared-trip safety applies to explicitly reviewed groups; independent visits on the same date/city are not collapsed automatically.

## Progress

- Current user clarification makes the earlier per-case travel assumption obsolete for the multi-case visit. Previous source-reading/layout evidence remains historical; replacement claim content requires fresh acceptance.
- Root and disjoint domain/UI worktrees created from the accepted local base. The candidate environment reconstructed with the locked existing versions; no dependency upgrade is planned.
- Domain/UI schema and visit-group guard agreed. Independent audit confirms the duplicate key must remain unchanged and travel-only needs attendance wording rather than a performed-service assertion.

- Independent UI review reproduced an initially unresolved visit recovering into multiple unmarked travel claims despite a shared-trip caption. The UI correction reconciles before review/queue boundaries and adds the actual harness regression. A second audit found random group IDs could bypass persisted shared-trip protection on re-upload; the default explicit cohort now needs an immutable source-hash identity. Distinct source files and explicit separate trips remain separate; this is not global date/city inference.
- Travel-only UI language was corrected to describe the requested fees, without asserting that no interpreting happened solely from the claim choice.

- Final immutable application checkpoint `8cfc8b9` assembles domain/UI corrections and portable registration. Independent code review accepted the final claim, grouping, persistence and malformed-record safeguards. Candidate and saved-checkout Full both passed 378 public synthetic tests and four isolated workflows; saved launch preflight passed at 8878. The initial fast checkpoint passed 155 tests before the two additional malformed-binding/date regressions.
- Real browser acceptance used the two captured source reads, preserving the earlier queue through source change. It moved/restored the shared owner, removed/restored cohort travel, refreshed all five reviews, queued six, ran non-writing preflight and prepared six separate replacement PDFs. All six rendered one-page documents passed exact content/profile checks and root/independent visual inspection. Only one shared-visit PDF claims travel. The replacement closing date is the current date; interpreting dates remain the two capture days.
- Fictional manual acceptance selected the available synthetic service profile, confirmed the default both-claim mode, selected travel-only and prepared a neutral attendance/sole-transport PDF with no service-tax paragraph. Root and independent visual inspection passed. Changing to interpreting-only cleared prepared links and stayed ready. Initial helper allowlist/default-profile mismatches were corrected in the isolated harness; they made no artifacts or external calls. An initial saved-replay path assertion was corrected before the passing read-only replay.
- The 19 public code/test paths were applied with byte verification and exact beforeimages. Saved-import replay returned six ready reviews and one shared-trip claimant; 22 protected entries were unchanged during application/replay. Final docs are applied separately, followed by the intended ignored standing-policy instruction update; 21 protected JSON entries remain unchanged. Saved branch/head and unrelated local work are retained.
- The new ignored result set contains six corrected PDFs, renders, acceptance/index and UI proof. The previous result index is explicitly superseded with exact beforeimages; its six PDFs and render bytes remain unchanged. All final PDFs passed root and independent review. Zero new provider calls, Gmail actions, real draft/index writes or publication. Owned servers stopped; owned IAB tab reset to blank. Local authorized objective complete; publication and user sending remain separate.
