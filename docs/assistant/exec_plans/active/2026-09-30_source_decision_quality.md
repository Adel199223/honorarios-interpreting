# Fee-request source and decision quality

## Goal and authorization

The user is dissatisfied with extraction, review usability and request quality, and explicitly authorized testing and improvements until the app works effectively. Compare the configured gpt-5.4-mini baseline with the requested gpt-5.6-terra and gpt-6.1-sol at high reasoning; verify the newly announced OpenAI Decisions API rather than assume access. Apply verified local improvements. New publication, live Gmail, main-app integration and destructive operations are outside this new scope.

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
- All three requested candidates completed the same six fictional image-only cases with the corrected prompt: 18/18 critical-field checks passed, estimated aggregate token cost USD0.1584 before cache adjustments. The requested gpt-6.1-sol/high setting is retained; this small clean-image set does not establish model superiority. Recorded median times were 2.27/3.05/8.10 seconds; outliers reached 43 seconds.
- Contextual rules, conservative AI/date merging, unknown locality handling, classification and trailing case punctuation were repaired. The independently labelled corpus now passes 39/39 cases with zero false-ready decisions or missing required questions; separate wrapped-date and procedural/place regressions extend the focused quality checks.
- Initial integrated Full passed 225 tests/four isolated workflows. Subsequent actual browser review found wrapped OCR date labels, an invisible Edit field under source-review CSS, misleading unresolved date attention after explicit confirmation and an invalid conflict-answer example. Those were reproduced and repaired; final Full is still required after integration.
- Actual sideways-photo recovery with gpt-6.1-sol/high found the critical fields; after wrapped-label repair it retains the performed date and asks only about its difference from EXIF capture date. Valid document confirmation, field correction focus, mobile width/keyboard navigation, PDF generation and manual handoff were observed. The one-page Portuguese PDF was rendered and manually inspected. No real Gmail call or local draft record was made.
- A generated-PDF regression found missing physical host wording when PJ service_entity differed from service_place; the shared body clause now includes the host. New default email templates opt into the selected PDF signature through a token; literal/private/request-specific email bodies stay unchanged.
- Final review found procedural date/context phrases mistaken for service places; seven durable reproductions and the parser fix pass. Explicit unknown-location evidence labels are being corrected before closing acceptance.

## Sources verified 2026-09-30

- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/api/docs/models/gpt-5.6-terra
- https://developers.openai.com/api/docs/guides/reasoning
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://developers.openai.com/api/docs/guides/evals

The [official DevDay recap](https://openai.com/index/devday-2026-recap/) confirms Decisions API was announced in limited preview. No public endpoint/schema or account preview access was established. Defer integration until those exist and a measured task benefits; this does not block the tested Responses improvements. See [source quality](../../../source-quality.md) for measured model results and verification sources.
