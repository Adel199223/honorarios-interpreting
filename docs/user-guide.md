# Create an interpreting fee request

LegalPDF Honorários helps turn an in-person interpreting notice into a Portuguese fee-request PDF and reviewed email-draft instructions. It keeps you in charge of checking the document and sending the email.

This guide describes the guided development interface recovered from your saved work. Its current acceptance and publication status are recorded in [the handoff](next-thread-handoff.md); an older published build may show a different layout.

## Open the app

Use the normal development launcher described in [setup](development-environment.md), then open the fee-app address it reports. The development helper normally uses `http://127.0.0.1:8878/`.

For real requests, confirm that the app is using your intended personal profile. A synthetic review session contains fictional details and must not be used to request payment.

## 1. Add your source

In **Start Interpretation Request**, choose one local notification PDF, photo or screenshot under **Add source file**, then click **Review source**. You can also drop a file or paste a copied screenshot into the source area.

Use an original/downloaded photo when possible. Uploading starts review; it does not create a fee PDF or send an email. If you have no source file, **Enter details manually** opens the manual path.

## 2. Check what the app found

In **Review Case Details**, read **What happened** and **Next safe action**, then check the five facts shown together: case, service date, paying authority, service place and recipient. **Edit** opens the matching field for correction. AI-read values and profile suggestions still need checking against the original source; the labels are not guarantees.

Expand **Show recovered details** or the detailed evidence when you need more context. When OpenAI reading is enabled, the source is read by OpenAI to suggest details. The default is GPT-6.1 Sol with high reasoning; source reading cost about one to three US cents in the fictional tests. See [the measured comparison and configuration](source-quality.md) for its limits and alternatives.

With your saved photo defaults enabled, the app uses the capture day as the interpreting day and the court in the photo's capture city as the payer. The five facts label these as **Your photo-date default** and **Your photo-city court default**. You do not need to confirm the same defaults on every photo. **Edit** still lets you enter an exception.

The capture city comes from photo location metadata or the photo viewer's location panel, not the police command's district. A configured city-court contact supplies the recipient; the app asks when date, city or court contact is missing or ambiguous. These are your workflow defaults, not facts printed on the document. A deliberately selected service profile or manual edit can supply a per-request exception. A different court named in the source remains visible evidence; it does not silently replace your default. See [photo preference configuration](source-quality.md#saved-photo-defaults).

The optional missing-venue rule uses the court in the capture city only when the source does not establish a physical service building. It appears as **Your photo-city court venue default · editable**. A police station or other venue identified in the source stays the service place, even if the court is paying. You can edit an exception or clear the default and answer the venue question. This rule is your saved preference, rather than proof of where the service occurred.

If the app identifies a translation request, duplicate or existing draft, read the warning before continuing. The ordinary PDF path stays blocked until the problem is resolved. Corrections use the explicit correction workflow, not a second normal request.

## Choose what to claim

In **What does this request claim?**, choose **Interpreting + travel** (the normal default), **Interpreting only**, or **Travel only**. Choose travel only when you are asking for the trip without asking for interpreting fees, such as when you attended but no work took place. The PDF describes attendance without claiming that interpreting was performed, and omits the interpreting-service tax statement. Choosing interpreting only removes the travel claim and the need to answer travel-distance questions.

These choices describe what you request; they do not decide whether the court owes a particular amount. Check the Portuguese draft and PDF after changing them. A request cannot proceed with neither claim selected.

## 3. Answer the missing questions

Type short answers using the displayed question numbers, then click **Apply answers**. For example, answer a date question with `1. 2026-09-30` only when that is the confirmed service date. In the review drawer, the same action is labeled **Apply numbered answers**.

The app reviews the request again. Continue only when no required questions or blocking warnings remain. You do not need to fill unrelated advanced fields merely because they are available.

Without the saved photo-date default, conflicting document/photo dates still ask which to use. With it enabled, the capture day takes priority and the previous printed-date candidate remains evidence. Missing or conflicting capture metadata still asks; you can always enter the actual service date as an exception.

## 4. Review and create the PDF

Use **Review draft and PDF step** to open the Portuguese draft text. Check the applicant, payment/service entities, case, service date, location and claimed travel details.

Then click **Create fee-request PDF**. Open the generated PDF or its preview and read it before preparing an email draft. If an inline image preview is unavailable, open the PDF itself; an unavailable preview is not confirmation that the document looks correct.

Changing the source or request details makes the old prepared result stale. Review again and create a fresh PDF before using its email handoff.

## Several cases in one photo

The review shows **Cases found in this source** when one photo contains several case references. Use **Review case** beside each row to check its facts and questions. Your field edits and unfinished numbered answers stay with that case when you switch. An unclear case remains visible until you correct it.

The **Travel for these source cases** controls start with **One shared trip** when the source's cases have matching visit facts. **Case that claims the shared trip** chooses the one PDF that includes travel. The first case is selected initially; the other cases retain their interpreting claims. This fits several cases handled during one journey. Choosing a travel-bearing claim on another case moves the shared trip to it. Check the previous owner's claim choice, especially if it previously claimed travel only.

Choose **Separate trips** only when separate journeys really occurred, or **No travel** when none of these requests should claim travel. Conflicting visit facts pause a shared trip until corrected; the app does not combine all requests merely because their city and day match. The shared-trip check also applies when explicitly grouped cases are prepared or recorded in separate batches. Re-uploading the same photo retains its shared-trip marker. A different or cropped photo and older history without that marker cannot establish whether travel was already claimed; check them yourself.

When every case is ready, click **Add all cases to batch** (the button includes the case count). The app checks each case again before adding the whole source. If one needs attention, it opens that case and leaves the queue unchanged. Adding cases only updates the queue; it does not create PDFs.

To include another photo, queue the current reviewed request or all its cases first, then use **Change source**. The previous queue stays in place while the next source starts with empty recovered text and capture metadata. Bulk adding a multi-case source selects separate fee-request PDFs. Check that every expected case appears in **Batch Queue**, leave **Packet mode** unchecked, run **Check batch preflight**, then use **Prepare batch package**. Review each generated PDF before any email step.

Editing a case after queueing pauses batch preparation until you review the correction and add the updated case or source to the queue. Do not rely on an earlier green batch check after changing details. **Reset workspace** clears the whole visible queue when you want to start over.

## 5. Prepare the email draft handoff

In **Manual Draft Handoff**, click **Build handoff packet**, check its recipient/body/attachments, then use **Copy handoff prompt**. Building or copying the packet does not create or send an email.

Check the email signature as well as the PDF signature. New default email templates use the selected personal profile's signature. Existing custom email wording stays as configured; an optional `{{signature_name}}` token makes a template follow the selected profile.

Use that exact prompt with your available Gmail draft tool or assistant to create an unsent draft. This external draft step is separate from preparing the PDF; if the draft tool is unavailable, keep the reviewed PDF and handoff packet until it is available. Direct Gmail OAuth is optional and is not required to review or prepare the document.

After the draft tool returns its response, paste it into **Paste Gmail _create_draft response**. Confirm the **Gmail handoff checklist** only after reviewing the PDF and using the exact handoff, then click **Record parsed response + prepared payload**. This records the returned draft locally so the app can warn against duplicate requests; it does not send the email.

Finally, open the draft in Gmail, check the recipient and attachments again, and send it yourself when satisfied. After sending, **Recent Work** can mark that request as manually sent.

## Start another request

Use **Change source** to keep queued requests while clearing the current review for another photo or document. Use **Reset workspace** for a clean visible workspace; it clears the current review and queue without deleting stored request history, generated files or Gmail drafts. If the app reports that its server is disconnected, restart the normal launcher and reload the page before continuing.

Batch tools, detailed source evidence, reference editing and direct Gmail setup are advanced paths. They can stay closed while you complete a single ordinary request.
