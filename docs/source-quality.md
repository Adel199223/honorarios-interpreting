# Source decisions and AI reading

The app should identify the date and place of the interpreting service, distinguish the paying authority from the physical host, and ask when an important fact is missing or conflicting. A document's issue date, closing date, appointment or photo capture date does not by itself establish when the service happened. Familiar profiles must not replace an unfamiliar court or city.

The beginner review shows case, service date, paying authority, service place and recipient together. Its origin labels describe how each value was obtained. AI-read values still need checking; an AI model repeating its own reading is not independent confirmation. The labels are categories, not measured probabilities. Capture metadata and explicit user confirmation remain distinct evidence.

## Saved photo defaults

The user can authorize standing photo rules through ignored `config/photo-defaults.local.json`, alongside the runtime's AI configuration. [The example](../config/photo-defaults.example.json) shows `capture_date_is_service_date`, `photo_city_court` and `missing_venue_is_city_court`. Each rule is opt-in; an absent file or disabled flag preserves the ordinary behavior for that rule. These preferences are separate from model/key settings and remain local.

The date rule selects one unambiguous capture day even when a printed service-date candidate differs. The city rule reads `photo_metadata_city` separately from document/service locality, then selects one configured `city_courts` record or one exact local court-directory match. Each configured city record supplies `payment_entity`, `recipient_email` and optionally `addressee`. Only a verified `tribunais.org.pt` contact is usable; the app does not construct an email from a city name or use the general email fallback for unresolved photo routing.

Policy-applied values are labeled as saved defaults and remain editable. A deliberately chosen service profile or manual edit is a per-request routing exception. A different source court remains evidence rather than automatically overriding the standing city rule. Payer/address/recipient/key are kept coherent during later profile review; source footer contacts cannot silently replace selected photo routing. Unknown city/contact or competing capture dates stay unresolved. Duplicate checks and PDF/preflight use the selected date normally. Notification PDFs and unconfigured runtimes retain their existing rules.

With `missing_venue_is_city_court` enabled, an absent physical service venue uses the uniquely configured court in the capture city. The UI labels it **Your photo-city court venue default · editable**. A source that establishes a police station, hospital or another physical host retains that venue even when the city-court rule selects the payer. A bare city, police command district or case suffix is not proof of the service building. This preference records the user's workflow rule; it does not turn a policy choice into a source fact. Without the venue preference, missing venue information still needs an answer.

Clearing a selected date, recipient or default venue keeps it unresolved through later profile review, including explicit-profile mode. Changing the payer clears its previous address/contact/key so an old court's recipient cannot survive a correction. A missing or ambiguous capture city/court cannot supply a venue default; enter the physical venue or resolve the routing information.

The current internal extraction prompt is `honorarios-source-multi-case-v4`, following `honorarios-source-photo-city-v3`. OCR still extracts source facts only. Standing photo rules run after extraction and are not represented as printed evidence or individual confirmation.

## Multiple cases in one photo

A source with several case references produces a visible list of separately reviewable requests. A single-case source keeps the ordinary flow. Each case uses the same immutable source evidence and image hash while retaining its own case number, effective intake, review and duplicate identity. Unreadable or ambiguous case rows stay visible and unresolved; they are not dropped or combined into one case number.

Switching cases preserves corrections and unapplied numbered-answer text for that case. Edited facts need another normal review before readiness is restored. **Add all cases to batch** is available only when every case is ready, then runs the ordinary review for every child again before changing the queue. A newly blocked review leaves the queue unchanged and opens the case that needs attention. Adding to the queue does not create any documents.

**Change source** clears the current review, recovered text and capture metadata while preserving previously queued requests. Bulk adding another photo keeps those earlier requests and selects separate PDFs rather than packet mode. Run the normal non-writing batch preflight before preparation. Editing an already queued source case requires fresh review and a queue update; stale preflight or prepared-review state cannot authorize a new PDF or handoff.

## Model configuration

Source recovery uses the existing OpenAI Responses API and strict structured output. The default is `gpt-6.1-sol` with `high` reasoning. Ignored `config/ai.local.json` can set `model`, `reasoning_effort` and `timeout_seconds`; environment overrides are `HONORARIOS_OPENAI_MODEL`, `HONORARIOS_OPENAI_REASONING_EFFORT` and `HONORARIOS_OPENAI_TIMEOUT_SECONDS`. Keep credentials in the existing ignored configuration or `OPENAI_API_KEY`; never include them in tests, reports or GitHub.

The default provider timeout is 90 seconds, output is capped at 8,192 tokens, responses use `store=False`, and automatic SDK retries are disabled. Failure or incomplete output is ignored and leaves manual review available. Provider error messages are not echoed into the app. Changing a model does not replace duplicate, recipient, date-conflict or PDF-review checks.

Official Sol and Astra model documentation supports image input, Responses and structured output. The bounded multi-case comparison below retains the same corrected extraction instructions and saved review policies. Keep this evidence separate from the earlier fictional comparison, and do not change the saved Sol/high default merely because Astra is available. [Sol model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Astra model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra).

## Bounded multi-case comparison, 2026-09-30

The updated Sol/high reader recovered the expected single case from one supplied photo and all five cases from the other. All six requests reached ready review under the configured photo policies. Astra/high read the same five-case photo with the updated instructions and recovered the same five cases, also ready. Source files, individual case references and generated artifacts stay ignored and local.

| Updated reader, same five-case photo | Exact cases recovered | Seconds | Input/output tokens | Estimated uncached USD |
| --- | --- | --- | --- | --- |
| gpt-6.1-sol, high | 5/5 | 33.58 | 3,407 / 1,223 | 0.0190 |
| gpt-6-astra, high | 5/5 | 29.95 | 3,407 / 1,387 | 0.1034 |

The bounded session used five provider calls: two baseline Sol reads, two updated Sol reads and one updated Astra read. The combined standard uncached token-price estimate was USD0.1875; cache discounts and invoice adjustments are excluded. On the five-case read, Astra was slightly faster and about 5.4 times the estimated cost, with the same recovery result. One handwritten sample does not establish general accuracy or speed superiority. Keep Sol/high as the app default; no model-setting change or Decisions API integration follows from this comparison. Ready source review alone does not establish final browser or rendered-PDF acceptance.

## Measured comparison, 2026-09-30

This earlier comparison used the same corrected extraction instructions and six fictional image-only documents for all candidates. Cases covered issue/performed dates, mixed formats, ambiguous dates, unfamiliar hospital locality, header/service locality and ordinary interpreting language containing `palavras`.

| Model and effort | Focused cases passed | Median seconds | Mean estimated USD/source |
| --- | --- | --- | --- |
| gpt-5.4-mini, none (old model default) | 6/6 | 2.27 | 0.0039 |
| gpt-5.6-terra, high | 6/6 | 3.05 | 0.0102 |
| gpt-6.1-sol, high | 6/6 | 8.10 | 0.0123 |

All 18 requests completed; the summed uncached token-price estimate was USD0.1584. Individual requests took 2.0–43.0 seconds, so the median is not a guaranteed response time. Estimates use recorded input/output usage and standard published prices; caching, regional charges and invoice adjustments are not included. No tools or external lookups were enabled in extraction.

The requested gpt-6.1-sol high setting passed and its cost is small for this workflow. This small clean-image set does not demonstrate that it is more accurate than either alternative. Improved instructions and deterministic rules are part of the result; it is not a model-only improvement. Fictional decision fixtures and provider-free replay checks are separate from actual vision/OCR measurement. Production accuracy on private documents remains unmeasured.

## Applied local acceptance

This section records the earlier source-decision-quality acceptance. The current multi-case/photo-venue work has separate results and publication status in [the handoff](next-thread-handoff.md); the historical counts below do not validate that newer scope.

Final candidate and saved-checkout Full passed 256 public synthetic tests and four isolated workflows. The 39 labelled decision cases pass with zero false-ready decisions or missing required questions; 64 focused quality tests include boundary regressions. These replay fixtures evaluate source decisions rather than broad OCR accuracy.

Actual fictional browser checks covered a native PDF without a provider call, a sideways photo with high-reasoning extraction, performed/capture-date confirmation, and an unreadable-date PDF that asked instead of guessing. The generated one-page request and its manual handoff were inspected. PDF physical hosts and new default email signatures retain the selected request details; literal custom email bodies remain unchanged. Corrections invalidate stale prepared files. See the [completed plan](assistant/exec_plans/completed/2026-09-30_source_decision_quality.md) for failed attempts and evidence limits.

## Decisions API

Verified 2026-09-30: OpenAI's September 29 DevDay 2026 announcement describes Decisions API as a limited preview that focuses Luna on user-defined questions with finite predefined answers and text/image context. It could later help classify interpreting vs translation, route a request or select a review action. These are potential app uses inferred from the announcement. It does not establish a replacement for extracting arbitrary case numbers, dates and venue text. [Official DevDay announcement](https://openai.com/index/devday-2026-recap/).

No public Decisions endpoint/schema or this account's preview access was established during this work. The app therefore continues using the tested Responses interface; do not invent a Decisions endpoint or add it solely because it was announced. Announced broad-release plans do not establish present account access.

Before a later integration, verify official availability/schema/account access, compare it against the existing labelled decision cases, and demonstrate a useful accuracy or latency improvement while retaining the review guards.

## Official sources checked 2026-09-30

- [GPT-6.1 Sol model, pricing and reasoning](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [GPT-6 Astra image input, Responses and structured-output support](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [GPT-5.6 Terra model and pricing](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [GPT-5.4 Mini model and pricing](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
- [Reasoning models](https://developers.openai.com/api/docs/guides/reasoning)
- [Structured output](https://developers.openai.com/api/docs/guides/structured-outputs)
- [DevDay announcement: Decisions API limited preview](https://openai.com/index/devday-2026-recap/)
