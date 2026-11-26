# Gmail authorization failure recovery

## Goal and scope

When token refresh definitively rejects authorization before draft creation, show a known not-created result, require reconnection for direct creation and preserve the reviewed PDF and Manual Draft Handoff. No automatic retry, provider/Gmail acceptance call, token deletion, private history migration or publication is included.

## Provenance and contracts

The isolated candidate starts from the current saved public snapshot after the completed source-history correction. Exact touched beforeimages remain private. Existing local overlays, selected accounts/scopes, prepared-source and duplicate guards, terminal attempts, actual records and prior artifacts stay authoritative. Ambiguous failures after draft-create POST retain their uncertain recovery path.

Only a token-endpoint refresh response with definitive `invalid_grant` records a secret-free rejection marker. Its revision binds relevant credentials while excluding transient OAuth state. Status reads never refresh tokens or write files; successful replacement credentials invalidate the marker. Existing token bytes are preserved on rejection.

## Steps and acceptance

1. Add typed refresh rejection, revision-bound local marker, secret-free status and not-created response.
2. Add UI recovery guidance and action gates without invalidating reviewed artifacts.
3. Run focused offline token/create/UI regressions, independent review and normal isolated UI acceptance.
4. Run integrated pinned Full once, then apply exact reviewed files and check the saved app without another live failure attempt.

## Risk and rollback

Do not label transient failures as revoked authorization or infer a draft absence after a draft-create request. Keep exact beforeimages, marker provenance and existing token files for rollback. A manual draft created separately must retain its genuine creation path and actual returned IDs; it must not turn a failed app attempt into successful app creation.

## Progress — 2026-11-12

- Created a source-only isolated candidate with zero initial privacy blockers and the pinned environment.
- Initial implementation checkpoint: implementation and offline acceptance were in progress; saved application and browser acceptance were pending.

- Typed refresh rejection, marker/status handling, explicit not-created response and artifact-preserving UI recovery are implemented. Repeated marked requests make no OAuth/draft POST and add no attempt; unrelated terminal failures are not relabeled.
- Successful callback repairs malformed marker state under the OAuth lock. Denial/transient failures retain appropriate existing credentials/status; no raw OAuth error body enters the new failure UI.
- Independent review accepted the implementation and follow-up recovery-consistency fixes. All 194 focused offline OAuth/backend/source-group/UI tests passed; syntax compilation passed. Final normal browser and Full results are recorded below.

- Root restarted the final frozen candidate and completed normal isolated browser acceptance with fictional credentials and the revision-bound rejection marker. Resume/review/reprepare restored the fictional request, showed the PDF/current args, recommended Manual Draft Handoff and built the handoff successfully. Reconnect-required status and the disabled direct-create action remained visible. No OAuth/Google/provider/record action was performed.
- Combined pinned `scripts/validate_dev.ps1 -Full` passed: 1,146 public tests and all four isolated workflows, plus environment, lock/dependency, documentation and JavaScript syntax checks. Clean source-only privacy review reported zero blockers/content findings.
- Pre-application checkpoint: exact saved application was pending. The user's later successful actual reauthorization and genuine manually created/recorded draft are separate private evidence and remain preserved. No marker was seeded against those newer working credentials from the older failure.


## Saved-app completion — 2026-11-12

- Root applied the exact eleven reviewed public files with all protected current records and credentials byte-identical. The owned saved server was restarted using the pinned launcher.
- Read-only status correctly reported the newer working Gmail connection, direct draft readiness, available Manual Draft Handoff, no reauthorization requirement and send disabled. No old rejection marker was seeded or token restored.
- Saved non-writing smoke completed successfully. The real earlier failed creation was not replayed, and the genuinely manually created/recorded draft and terminal not-created app attempt remained distinct and intact.
- The authorized correction is complete locally. Full was not repeated after exact application; implementation acceptance made no real provider/Gmail call and no canonical history migration or publication. Private apply, browser and smoke receipts retain exact evidence.
