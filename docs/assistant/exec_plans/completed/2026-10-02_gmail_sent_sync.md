# Gmail sent-status synchronization — 2026-10-02

## Goal and authorization
The user accepted automatic checks on entering Recent Work plus Sync now, following manual sending in Gmail. Add bounded Gmail reads and update only reliably verified local sent status. This specific approval extends the older no-mailbox-search restriction for this feature. No email sending, remote mutation, draft creation/deletion, OpenAI call, publication or LegalPDF integration is authorized.

## Provenance and preserved contracts
Continue the existing Photos/readiness candidate at published base a0ed383 and preserve the saved app's earlier local overlays. Preserve request case/date/period identity, all grouped children and attachments, shared travel ownership, freshness and duplicate guards. Missing drafts and uncertainty remain protected. Preserve original draft/message identifiers, retaining separate sent evidence.

## Steps and acceptance
1. Implement bounded exact Sent matching, incremental read authorization and an atomic guarded local lifecycle transition.
2. Add accessible Recent Work status, automatic route-entry checks and Sync now without disturbing unfinished source work.
3. Test synthetic sent/grouped/still-draft/missing/ambiguous/error/concurrency/OAuth cases with no provider calls. Independently review the patch and exercise the ordinary browser.
4. Run the pinned portable Full suite and four isolated workflows in candidate and saved app; apply only touched files with exact beforeimages.
5. Check existing read authorization, request Google consent only if necessary, and perform the approved bounded live read acceptance. Never send a test message.

## Risks and rollback
Gmail gives sent messages new IDs. Require SENT evidence, exact recipient and subject, attachment hash multiset and a valid send timestamp. Unverifiable or changed local records stay unchanged. Serialize synchronization and revalidate under the shared history lock; write blocking duplicate state before finalizing the log. OAuth denial/partial grants must preserve working credentials. Ignored task evidence retains beforeimages, protected-state hashes and acceptance receipts; restore only this scope's files if needed.

## Progress
- 2026-10-02: Active implementation; backend matching, frontend and independent review delegated. Existing manual sent workflow retained. No live calls in this implementation stage.

- 2026-10-02: Complete locally and applied to the saved app. Independent review passed 56 focused checks (28 engine, 16 OAuth/API/domain, 12 UI). The first Full run identified stale test membership expectations and a callback mock argument, both corrected without relaxing assertions. Final candidate and saved Full each passed 887 public tests and four isolated workflows.
- Ordinary isolated browser acceptance automatically updated two fictional emails/four child requests, retained one existing draft and one unconfirmed missing draft, then made no duplicate transition on Sync now. Provider HTTP was disabled in that process. Scoped private evidence and screenshots are retained in the ignored task folder.
- All five current saved draft emails passed the unchanged reviewed-payload/attachment binding check. An obsolete private OAuth callback port was corrected to the verified saved server. The user granted additional Gmail read access through Google. The first live browser Sync now checked five actual drafts: all five still exist, zero sent changes, zero uncertain results and zero errors. Exact Sent matching and grouped transitions were verified synthetically; no actual email was sent merely to test them.
- Of 1,709 prior protected files, 1,707 are byte-identical. Only the expected private Gmail callback setting and OAuth token changed; an OAuth lock file may be added. Draft log, duplicate index, attempts, source files, PDFs and other settings remain unchanged. Beforeimages, exact apply hashes and separate validation/live receipts are retained. Temporary browser/server resources are closed; the usual app remains at 8878 with the successful result visible and unfinished browser work retained.
- No OpenAI call, remote Gmail mutation, new draft/PDF, publication or LegalPDF integration occurred. The approved scope is complete; broader/provider operations require their own task scope.

## Sent classification correction

The user correctly reported that the five emails had already been sent. The preceding "five still drafted" acceptance result was wrong: Gmail returned HTTP 200 for the old draft IDs, but every nested message had the SENT label and no DRAFT label. The engine incorrectly treated resource existence as an unsent draft and skipped Sent matching. Direct read-only checks using this app's OAuth verified all five sent messages against the exact six reviewed PDF bytes, recipients, subjects and creation/send times. The old report below is preserved as history and is superseded by this correction.

Synchronization now searches exact Sent evidence for every eligible request first. Only a completed search without an exact match may fall back to a validated DRAFT-labelled resource; missing, contradictory or unexpected labels retain protection for review. Existing resources, surviving draft copies and failed draft lookups cannot hide a verified Sent match. Timestamp, attachment, grouped-child, immutable-evidence, concurrency and resource-budget guards remain intact. Synthetic regressions cover the actual 200/SENT response and the separate surviving-copy case.

Independent review passed. Candidate and saved Full each passed **890 public tests and four isolated workflows**. The normal saved browser automatically synchronized **five sent emails and all six fee requests**, with zero remaining drafts in this group, zero uncertain results and zero errors. Only the five corresponding draft-log rows and six duplicate-index rows changed; original IDs, all earlier history, PDFs, claims, shared-trip ownership and other fields remain intact. Exact beforeimages, independent Gmail read evidence, apply hashes, tests and the final screenshot are under ignored `tmp/gmail-sent-sync-correction-2026-10-02/`. The usual app remains at 8878. No mail was sent, deleted or changed, and no OpenAI call, new fee PDF, new draft, publication or LegalPDF integration occurred.

