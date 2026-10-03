# Source decisions and AI reading

The app should identify the date and place of the interpreting service, distinguish the paying authority from the physical host, and ask when an important fact is missing or conflicting. Notification PDFs use an explicit interpreting appointment date as the editable service-date default. Issue, certification, closing and file dates do not supply that default. Photos follow the separate saved capture-day rule below. Familiar profiles must not replace an unfamiliar court or city.

## Notification PDFs and mixed work

For a notification, read the interpreter's attendance or performed-service clause, including Portuguese written dates, independently of the notice's issue date. Missing, conflicting, cancelled or unrelated appointments require review. A scheduled appointment supplies a drafting default; it is not proof that interpreting took place. The claim selector remains authoritative for interpreting, travel or both.

A notice can assign in-person interpreting and separate written translation. When the interpreting assignment is explicit, prepare only that interpreting request and explain that written translation is excluded. Ambiguous mixed notices ask a numbered scope question; its answer is tied to that source. Translation-only notices remain set aside. Classification does not waive date, case, venue, recipient or duplicate checks.

Every visible PDF case is reviewed separately, like a multi-case photo, and produces its own PDF. One email per source groups compatible child attachments; differing dates/venues do not automatically establish a shared trip. Replacing a source clears its old supporting files and custom email text; re-reading the same source keeps them.

Source reading remains bounded: at most eight text pages or three pages requiring image recovery. If pages remain unread, rendering/OCR fails, or the PDF exceeds those limits, upload stops and explains how to supply a shorter relevant-page PDF or complete reviewed text. A readable first page cannot establish that the rest was read. Source-read limits are separate from generated-request page counts.

Configured short ordinary-court labels can also apply to a notification when the visible court and exact recipient uniquely match that saved preference. Raw source wording remains evidence; specialized courts, unknown recipients and different physical hosts are not shortened by guesswork. The saved closing city applies independently of source/service-profile detection, while explicit edits and clears remain authoritative. AI-extracted summons instructions remain evidence and cannot become the fee request's location clause.

The beginner review shows case, service date, paying authority, service place and recipient together. Its origin labels describe how each value was obtained. AI-read values still need checking; an AI model repeating its own reading is not independent confirmation. The labels are categories, not measured probabilities. Capture metadata and explicit user confirmation remain distinct evidence.

Original-photo metadata reading supports large sequential JPEGs through bounded reduced decoding while retaining the original bytes, dimensions and EXIF. Large progressive/non-interleaved or oversized images still stop when they cannot be decoded within the limits; other formats keep their existing guards. The app does not resize or replace the source original to recover its metadata.

Only one source recovery may be pending across upload, drop, paste and Google Photos import. Changing a file timestamp does not start a parallel read. Resetting or changing source invalidates late results, while the pending operation remains guarded until it finishes. New preparation still requires the current source's normal review.

## Saved photo defaults

The user can authorize standing photo rules through ignored `config/photo-defaults.local.json`, alongside the runtime's AI configuration. [The example](../config/photo-defaults.example.json) shows `capture_date_is_service_date`, `photo_city_court`, `missing_venue_is_city_court` and `missing_gnr_venue_is_capture_city`. Each rule is opt-in; an absent file or disabled flag preserves the ordinary behavior for that rule. These preferences are separate from model/key settings and remain local.

The date rule selects one unambiguous capture day even when a printed service-date candidate differs. The city rule reads `photo_metadata_city` separately from document/service locality, then selects one configured `city_courts` record or one exact local court-directory match. Each configured city record supplies `payment_entity`, `recipient_email` and optionally `addressee`. Only a verified `tribunais.org.pt` contact is usable; the app does not construct an email from a city name or use the general email fallback for unresolved photo routing.

An optional `verified_gps_areas` list supplies local city evidence when original EXIF GPS falls inside a previously verified area. Each entry requires `city`, numeric `latitude`/`longitude`, `radius_m` greater than zero and at most 500, and an HTTPS `source_url` identifying the verification source. Use at most 100 areas; an absent or empty list disables matching. The application does not fetch those URLs, verify a catalog on its own, call a geocoder or choose the nearest city outside an area. Configure only checked city areas, never use a broad district radius. The public example leaves the list empty.

The whole enabled catalog must validate. Invalid entries, areas overlapping different cities, or disagreement with embedded/visible/AI capture-city evidence leave routing unresolved and expose the normal source-bound city question. Multiple matching areas for the same normalized city are one choice. Raw EXIF and embedded city names stay unchanged; derived evidence is labeled **GPS matched a verified local area** and keeps its local verification citation. This city inference does not establish a physical building. It is added after source recovery, so private area definitions and citations do not become AI input and no extra provider read occurs. A manual city answer or payer/venue exception remains authoritative.

An independently optional `verified_gps_venues` list can suggest an editable physical venue when a specific source heading and original GPS agree. Each verified entry supplies `id`, `city`, `service_entity_type`, `service_entity`, `service_place`, numeric `latitude`/`longitude`, a positive `radius_m` no greater than **200**, `required_source_phrases`, and one or more HTTPS `source_urls`. At most 100 entries are allowed. The public example leaves this list empty. Configure only independently checked public premises and a source-specific unit/address pattern; no location is fetched, geocoded or learned automatically.

Every configured phrase must match the source's own bounded heading, including the agency, the named city and a specific unit or address. The service entity type must agree; supported agencies are GNR, PSP, Polícia Judiciária and Ministério Público, including DIAP. An agency plus a city alone is insufficient. Exactly one valid configured venue must match the original EXIF GPS circle and all source phrases. Invalid configuration, missing or conflicting city/GPS, several matching premises, quoted agency contacts, or another explicit physical venue leave the ordinary question unresolved. A deliberately selected profile, manual venue or deliberate field clear takes priority. An inherited generic court type can be corrected only when an automatic fallback's named agency and its own source heading independently agree.

Review labels a successful result as an **editable GPS + source venue default**, separate from a printed location. Its evidence retains the source hash, matched phrases, distance and verification citations locally. GPS proximity is an inference about the likely premises, not proof of an exact room, attendance or interpreting. The proposal changes no payer, recipient or distance directly; ordinary saved routing and travel rules, user edits, freshness checks and PDF review remain authoritative. Private venue definitions are applied after the provider boundary, without another AI call.

Policy-applied values are labeled as saved defaults and remain editable. A deliberately chosen service profile or manual edit is a per-request routing exception. A different source court remains evidence rather than automatically overriding the standing city rule. Payer/address/recipient/key are kept coherent during later profile review; source footer contacts cannot silently replace selected photo routing. Unknown city/contact or competing capture dates stay unresolved. Duplicate checks and PDF/preflight use the selected date normally. Notification PDFs and unconfigured runtimes retain their existing rules.

With `missing_venue_is_city_court` enabled, an absent physical service venue uses the uniquely configured court in the capture city. The UI labels it **Your photo-city court venue default · editable**. A source that establishes a police station, hospital or another physical host retains that venue even when the city-court rule selects the payer. A bare city, police command district or case suffix is not proof of the service building. This preference records the user's workflow rule; it does not turn a policy choice into a source fact. Without the venue preference, missing venue information still needs an answer.

With `missing_gnr_venue_is_capture_city: true`, a photo with its own explicit GNR heading and one independently supported capture city can default an otherwise missing venue to **GNR de <city>**. This is an editable user preference: the exact street or building need not be identified. City evidence must come from local capture metadata, a verified GPS city area or the user's answer bound to that photo; an AI city guess or command/district heading alone cannot supply it. The app retains separate court-payer routing and uses the ordinary saved travel lookup. A more specific verified GPS/source venue, named station or other explicit physical host takes priority.

This GNR policy does not apply to notification PDFs, PSP/MP sources, PJ context, conflicting agency/city evidence, quoted GNR contacts, deliberately selected profiles, manual venues or intentional field clears. Its provenance is labeled as a GNR capture-city default and remains bound to the current photo, source text and selected values. It does not claim that GPS identified a particular building or established attendance. Later venue changes reconcile generated wording and untouched travel defaults; manual distances, zero, claim choices and shared-trip ownership remain authoritative.

On an initial automatic upload, an independently supported capture city can also disambiguate an existing GNR service profile when the issuer's own postal heading names that same city and the profile's saved travel destination matches it. An enabled photo-city court rule takes priority; the profile routing fallback cannot replace any configured city contact, including an ambiguous or incomplete entry. It retains that known profile's payer, contact and distance only when city-court routing is disabled or entirely absent, while labeling the generic GNR venue separately. An address in the document body cannot trigger this selection, and the app does not create a new profile from the match.

Other source-grounded noncourt agencies without a physical host or eligible verified GPS/source venue leave the venue unresolved instead of substituting the paying court. GNR does too when its separate preference is disabled or its requirements are unmet. The app asks one building/city question and retains the city-court payer preference; a generic empty `other` type alone is insufficient agency evidence. An explicit venue answer remains authoritative, and PJ context still requires its physical host.

Clearing a selected date, recipient or default venue keeps it unresolved through later profile review, including explicit-profile mode. Changing the payer clears its previous address/contact/key so an old court's recipient cannot survive a correction. A missing or ambiguous capture city/court cannot supply a venue default; enter the physical venue or resolve the routing information.

The current internal extraction prompt is `honorarios-source-foreground-scope-v7`. Corroborated cropped agency letterhead can preserve a noncourt agency without inventing its physical host. A local pattern applied to AI-read text remains labeled as AI evidence. OCR still extracts source facts only. Standing photo rules run after extraction and are not represented as printed evidence or individual confirmation.

Source recovery keeps the intended foreground document or document group separate from incidental background sheets. Foreground text and case references drive review; background OCR is retained as separate visible evidence and does not create fee requests. Genuine foreground multi-case tables and folder groups retain every case. Uncertain document boundaries or contradictory foreground/background readings withhold case identities for source review instead of silently choosing or discarding a case. Legacy stored recoveries remain readable; fresh source reading uses this foreground contract.

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

Actual human-style browser review subsequently found one omitted AI venue field while the source still named a station as its entity. Source-grounded station handling repaired that route without changing the reader model. The final workflow produced all six separate PDFs, each accepted through rendered-page and independent fact review. Browser repetitions and saved-import checks replayed the captured actual provider responses; they were not additional vision calls. Final candidate and saved-checkout Full passed 330 public synthetic tests and four isolated workflows. Prepared mixed-city summaries now display facts from the prepared snapshot rather than the currently selected source. See [the completed plan](assistant/exec_plans/completed/2026-09-30_six_case_photo_acceptance.md) for local application, publication status and evidence limits.

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
