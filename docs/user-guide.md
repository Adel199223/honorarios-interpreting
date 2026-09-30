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

Check the actual interpreting service date. A date suggested from a photo can be its capture date. Use the suggested date only if the service happened then; otherwise choose another date or leave it unresolved until you know.

If the app identifies a translation request, duplicate or existing draft, read the warning before continuing. The ordinary PDF path stays blocked until the problem is resolved. Corrections use the explicit correction workflow, not a second normal request.

## 3. Answer the missing questions

Type short answers using the displayed question numbers, then click **Apply answers**. For example, answer a date question with `1. 2026-09-30` only when that is the confirmed service date. In the review drawer, the same action is labeled **Apply numbered answers**.

The app reviews the request again. Continue only when no required questions or blocking warnings remain. You do not need to fill unrelated advanced fields merely because they are available.

If document and photo dates differ, the question shows both dates. Answer the actual service date, or use `document` or `metadata` only when that is correct. Once confirmed, the difference remains recorded as resolved evidence.

## 4. Review and create the PDF

Use **Review draft and PDF step** to open the Portuguese draft text. Check the applicant, payment/service entities, case, service date, location and claimed travel details.

Then click **Create fee-request PDF**. Open the generated PDF or its preview and read it before preparing an email draft. If an inline image preview is unavailable, open the PDF itself; an unavailable preview is not confirmation that the document looks correct.

Changing the source or request details makes the old prepared result stale. Review again and create a fresh PDF before using its email handoff.

## 5. Prepare the email draft handoff

In **Manual Draft Handoff**, click **Build handoff packet**, check its recipient/body/attachments, then use **Copy handoff prompt**. Building or copying the packet does not create or send an email.

Check the email signature as well as the PDF signature. New default email templates use the selected personal profile's signature. Existing custom email wording stays as configured; an optional `{{signature_name}}` token makes a template follow the selected profile.

Use that exact prompt with your available Gmail draft tool or assistant to create an unsent draft. This external draft step is separate from preparing the PDF; if the draft tool is unavailable, keep the reviewed PDF and handoff packet until it is available. Direct Gmail OAuth is optional and is not required to review or prepare the document.

After the draft tool returns its response, paste it into **Paste Gmail _create_draft response**. Confirm the **Gmail handoff checklist** only after reviewing the PDF and using the exact handoff, then click **Record parsed response + prepared payload**. This records the returned draft locally so the app can warn against duplicate requests; it does not send the email.

Finally, open the draft in Gmail, check the recipient and attachments again, and send it yourself when satisfied. After sending, **Recent Work** can mark that request as manually sent.

## Start another request

Use **Reset workspace** for a clean visible workspace. It clears the current review and queue without deleting stored request history, generated files or Gmail drafts. If the app reports that its server is disconnected, restart the normal launcher and reload the page before continuing.

Batch tools, detailed source evidence, reference editing and direct Gmail setup are advanced paths. They can stay closed while you complete a single ordinary request.
