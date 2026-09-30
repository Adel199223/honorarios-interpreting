# Fee-request source and decision quality

## Goal and authorization

The user is dissatisfied with extraction, review usability and request quality, and explicitly authorized testing and improvements until the app works effectively. Compare the configured gpt-5.4-mini baseline with the requested gpt-5.6-terra and gpt-6.1-sol at high reasoning; verify the newly announced OpenAI Decisions API rather than assume access. Apply verified local improvements. The initial development scope excluded publication, live Gmail, main-app integration and destructive operations; the publication follow-up below records subsequent authorization.

## Provenance and preservation

- Published base: PR #59 / main f792c95ef072fa94192dbb4ecdc4862d91b5797d.
- Authoring branch: codex/fee-quality-improvement-20260930; parallel scopes use separate quality-rules, quality-tests and quality-review worktrees from the same base.
- Preserve original saved branch/history, current private runtime, all earlier acceptance artifacts and dependency versions.
- Paid model comparisons are authorized by the user's current testing request. Use fictional documents first, store no responses at the provider, cap the initial comparison at USD5 and a bounded number of calls, record usage/latency and outstanding/uncertain calls. No automatic retry loops.

## Work and evidence

1. Verify official model/Decisions guidance and actual existing-key access without exposing credentials.
2. Define labelled fictional scenarios for performed vs issue/appointment dates, mixed date formats, header vs service locality, unknown courts, PJ host locations, interpreting vs translation language, travel and recipient/duplicate rules. Record baseline failures.
3. Repair contextual date/place/profile/classification rules while preserving public routes/payloads and existing date/duplicate/recipient/Gmail contracts. Uncertainty must ask rather than silently choose.
4. Correct AI prompt/evidence handling and add intentional validated reasoning/model configuration with bounded provider deadlines and secret-free failure reporting. Compare requested candidates on the same source cases and retain the measured choice.
5. Make uncertain or inferred facts understandable in the beginner review. Keep technical evidence optional, and inspect actual PDF/photo -> answers -> preview -> handoff behavior.
6. Run focused benchmark/regressions, model quality/cost/latency comparisons, final Full, actual browser/mobile/keyboard review and rendered fictional PDF inspection. Apply only verified changes with exact beforeimages; preserve private settings except the explicitly intended model/reasoning configuration changes.

## Acceptance

- The labelled source scenarios have no confidently wrong service date, place, payment entity or recipient; missing/ambiguous facts ask appropriate questions.
- Newer high-reasoning model access and quality are demonstrated by actual bounded calls, not metadata alone; report measured cost, latency and failures. Decisions API is used only if its official contract and access are established and a measured task benefits.
- Review shows the important facts and uncertainty clearly, retains edits and freshness protections, and produces a manually inspected correct Portuguese PDF and manual handoff.
- Public synthetic Full and four isolated workflows pass; browser acceptance uses isolated runtime. No Gmail send, real draft creation, provider credential publication or main-app data changes.
- Daily saved app contains the verified source/configuration; exact beforeimages and original branch/history remain available.

## Progress

- Existing provider configuration reports gpt-5.4-mini; the app already uses Responses with strict structured output and store=False. Metadata access lists all three comparison candidates.
- Provider-free probes exposed first-date selection, ISO-over-EU date selection, mismatched labour-court profile, header/service-city confusion, broad words/translation classification and unfamiliar PJ-host locality issues. These are concrete source-rule defects; current synthetic checks do not establish broad OCR accuracy.
- All three requested candidates completed the same six fictional image-only cases with the corrected prompt: 18/18 requests passed their critical-field checks, estimated aggregate token cost USD0.1584 before cache adjustments. The requested gpt-6.1-sol/high setting is retained; this small clean-image set does not establish model superiority. Recorded median times were 2.27/3.05/8.10 seconds; outliers reached 43 seconds.
- Contextual rules, conservative AI/date merging, unknown locality handling, classification and trailing case punctuation were repaired. The independently labelled corpus now passes 39/39 cases with zero false-ready decisions or missing required questions; separate wrapped-date and procedural/place regressions extend the focused quality checks.
- Initial integrated Full passed 225 tests/four isolated workflows. Subsequent actual browser review found wrapped OCR date labels, an invisible Edit field under source-review CSS, misleading unresolved date attention after explicit confirmation and an invalid conflict-answer example. Those were reproduced and repaired; final integrated and independently applied Full both passed 256 tests and four isolated workflows.
- Actual sideways-photo recovery with gpt-6.1-sol/high found the critical fields; after wrapped-label repair it retains the performed date and asks only about its difference from EXIF capture date. Valid document confirmation, field correction focus, mobile width/keyboard navigation, PDF generation and manual handoff were observed. The one-page Portuguese PDF was rendered and manually inspected. No real Gmail call or local draft record was made.
- A generated-PDF regression found missing physical host wording when PJ service_entity differed from service_place; the shared body clause now includes the host. New default email templates opt into the selected PDF signature through a token; literal/private/request-specific email bodies stay unchanged.
- Final review found procedural date/context phrases mistaken for service places; seven durable reproductions and the parser fix pass. Explicit unknown-location evidence now identifies document text without claiming a configured destination match; AI-only readings remain unverified.

## Sources verified 2026-09-30

- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/api/docs/models/gpt-5.6-terra
- https://developers.openai.com/api/docs/guides/reasoning
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://developers.openai.com/api/docs/guides/evals

The [official DevDay recap](https://openai.com/index/devday-2026-recap/) confirms Decisions API was announced in limited preview. No public endpoint/schema or account preview access was established. Defer integration until those exist and a measured task benefits; this does not block the tested Responses improvements. See [source quality](../../../source-quality.md) for measured model results and verification sources.

## Local completion, 2026-09-30

- Final tested application code: `5b3c53d`; public changes are applied byte-for-byte to the usual saved checkout. Its existing branch/history remain unchanged. All 18 protected existing local files are hash-unchanged; the intended ignored AI settings now select gpt-6.1-sol/high, with existing credential availability and unrelated settings preserved. Exact public beforeimages and application receipts remain in ignored local evidence.
- Final Full passed 256 public synthetic tests and four isolated workflows in both the assembled candidate and saved checkout. The focused quality group contains 64 tests, including 39 labelled decision cases; zero false-ready decisions or missing required questions remain in those cases. Environment/lock, offline installed-wheel, JavaScript syntax and routing checks passed. Saved launch preflight passed at port 8878.
- Fresh native-PDF acceptance exposed a soft line wrap that shortened a physical court name to its city. Four failing wrap cases and negative blank-line/sentence/header boundaries were added before a conservative continuation fix. The actual native PDF now retains the full court, performed date and recipient; it needs no provider call. Ready-step wording was clarified after actual review revealed contradictory blocked copy.
- Final sideways-photo acceptance used gpt-6.1-sol/high, retained the performed 26 September date, distinguished the 28 September EXIF capture date, and asked one question showing both dates. The displayed `1. document` answer was applied through the normal backend. Readiness and optional attention became resolved while the capture evidence and AI origin labels remained visible.
- The final native-PDF request was prepared, rendered and manually inspected: one legible Portuguese page, correct case, court, service/closing dates and selected applicant, with no unclaimed travel wording. Poppler reported missing display-font aliases but rendering succeeded and the inspected image was legible. The default email handoff uses the same applicant as the PDF; custom/literal bodies remain unchanged. Its one-attachment packet was inspected without contacting Gmail or recording any draft IDs.
- A real field correction after preparation focused the visible input and immediately made the earlier preparation stale, clearing preview/handoff controls. Previously completed mobile width and keyboard checks passed. An issue-only PDF with an unreadable service date performed the intended AI cross-check, left the service date blank and asked instead of choosing its issue date; no request artifact for that case was created.
- All 18 comparison calls and four bounded fictional browser calls completed. Their summed uncached token-price estimate is about USD0.2342, below the initial USD5 cap; no outstanding or uncertain call remains. Browser calls took 9.5–26.6 seconds. These are clean fictional sources, not a production-accuracy claim for private paperwork.
- The owned synthetic server is stopped, its browser viewport reset and temporary tab blank. Runtime package versions remain pinned. No new plugin, installation, real Gmail action, main-app change or publication was performed.

The authorized local improvement is complete. The user subsequently authorized publication of this new scope as recorded below. Testing private real documents and future main-app integration remain separately scoped. Decisions API integration is deferred until official public contract/account access and a measured benefit are established; this does not prevent use of the improved app.


## Authorized publication follow-up, 2026-09-30

After the validated improvement was applied locally, the user explicitly requested publication. [PR #60](https://github.com/Adel199223/honorarios-interpreting/pull/60) targets main from the integrated quality branch. The fetched approved baseline remains `f792c95`; no newer accepted work is missing. An independent final diff review found no new code/contract blockers. Tracked privacy checks passed 114 files/zero blockers and the pre-commit gate is configured.

The earlier candidate/saved Full and browser acceptance cover unchanged application code. This publication changes current documentation status only; documentation routing and privacy checks are repeated. Merge is authorized when hosted checks for the current PR head pass and unresolved review blockers are absent. Use the PR's check/merge record to establish GitHub main availability; do not infer it from this pre-merge closeout text. Preserve saved branch/history, all configuration/data hashes and local acceptance beforeimages; public publication excludes private documents, provider settings, credentials and generated outputs.

The first hosted run `36755591678` failed four UI/guidance assertions because Node's UTF-8 output was decoded through the hosted Windows legacy code page. A local code-page reproduction failed the same four assertions; explicit UTF-8 on the three test subprocess boundaries repaired it without changing application behavior. The local reproduction and Full are rerun, and the current PR-head hosted run must pass before merge. The failed run and before/after logs are retained in ignored publication evidence.
