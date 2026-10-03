# Create an interpreting fee request

LegalPDF Honorários helps turn an in-person interpreting notice into a Portuguese fee-request PDF and reviewed email-draft instructions. It keeps you in charge of checking the document and sending the email.

This guide describes the guided development interface recovered from your saved work. Its current acceptance and publication status are recorded in [the handoff](next-thread-handoff.md); an older published build may show a different layout.

## Open the app

Use the normal development launcher described in [setup](development-environment.md), then open the fee-app address it reports. The development helper normally uses `http://127.0.0.1:8878/`.

For real requests, confirm that the app is using your intended personal profile. A synthetic review session contains fictional details and must not be used to request payment.

## 1. Add your source

In **Start Interpretation Request**, choose one local notification PDF, photo or screenshot under **Add source file**, then click **Review source**. You can also drop a file or paste a copied screenshot into the source area.

When your phone Camera folder is configured, **Add source file** opens a grid of photo previews with filenames underneath. Choose the picture you recognize, then click **Review source**. Keep the phone connected while previews load. Search by date or filename and use Previous/Next for more photos. If a preview says the photo changed or is unavailable, click **Refresh photos** to reload the current page and try again. This keeps your search and selected source. Browsing the grid does not use AI; selecting a tile imports the original with its available date and location metadata. **Choose another file** opens the ordinary file picker.

Use an original/downloaded photo when possible. Uploading starts review; it does not create a fee PDF or send an email. If you have no source file, **Enter details manually** opens the manual path.

While a source is being read, wait for its result before uploading, dropping, pasting or importing another source. Changing source or resetting clears the old review; a delayed result cannot become the new request. The app keeps the pending read guarded until it finishes.

To choose a photo from your Google Photos account, click **Google Photos** in the top bar. This opens the source options and keeps your current work. If necessary, use **Connect Google Photos OAuth**, then **Open Google Photos Picker**. Select one image, finish the selection in Google Photos, and return to **Import Picker selection**. **Check Picker selection** shows whether your selection is ready. A saved authorization needs a successful Picker operation to establish current access.

You can also download the original photo yourself and select it under **Google Photos selected-photo import**. The optional metadata box accepts a capture city or date from the photo's details. A screenshot of those details is unnecessary when the original already contains the required capture metadata. See [Google Photos and original-photo metadata](google-photos.md) for the remaining location limits and setup.

## 2. Check what the app found

In **Review Case Details**, read **What happened** and **Next safe action**, then check case, service date, paying authority, service place and recipient. Photos also show the capture city used by your defaults. **Edit** opens the matching request field for correction; the city row explains its evidence. AI-read values and profile suggestions still need checking against the original source; the labels are not guarantees.

Expand **Show recovered details** or the detailed evidence when you need more context. When OpenAI reading is enabled, the source is read by OpenAI to suggest details. The default is GPT-6.1 Sol with high reasoning; source reading cost about one to three US cents in the fictional tests. See [the measured comparison and configuration](source-quality.md) for its limits and alternatives.

With your saved photo defaults enabled, the app uses the capture day as the interpreting day and the court in the photo's capture city as the payer. The facts label these as **Your photo-date default** and **Your photo-city court default**. You do not need to confirm the same defaults on every photo. **Edit** still lets you enter an exception.

Original-photo capture metadata is used when available; the file's modification date does not establish when you interpreted. The app keeps the camera's local capture day and any recorded UTC offset. A Google Photos timestamp without original EXIF needs an explicit saved capture timezone or your date answer; the computer's current timezone is not assumed. If the capture date or city is missing, supply the missing fact. Clearing a required reviewed field asks for it again instead of silently restoring a default. An unclear or fragmented case number also needs correction before preparation.

The capture city comes from photo location metadata or the photo viewer's location panel, not the police command's district. A configured city-court contact supplies the recipient; the app asks when date, city or court contact is missing or ambiguous. These are your workflow defaults, not facts printed on the document. A deliberately selected service profile or manual edit can supply a per-request exception. A different court named in the source remains visible evidence; it does not silently replace your default. See [photo preference configuration](source-quality.md#saved-photo-defaults).

With your saved photo-city defaults enabled, a missing capture city produces one numbered city question. Answer it once for the reviewed photo; the app checks the saved court, contact, missing venue and travel defaults without another AI read. A named physical venue or your manual exception stays authoritative. An unknown or ambiguous court/contact still requires an answer.

An original file can supply an embedded capture city or GPS inside a locally configured verified city area. The latter appears as **GPS matched a verified local area**; it is a city inference and does not prove the service building. The app asks when areas conflict or other capture-city evidence disagrees, and it never chooses a nearest city outside the verified areas. Google Photos API downloads omit location metadata, so the Picker path usually still needs your capture city. A city shown in the photographed document is a separate fact.

The optional missing-venue rule uses the court in the capture city only when the source does not establish a physical service building. It appears as **Your photo-city court venue default · editable**. A police station or other venue identified in the source stays the service place, even if the court is paying. You can edit an exception or clear the default and answer the venue question. This rule is your saved preference, rather than proof of where the service occurred.

If the source identifies a police agency but omits its physical host, answer the building/city question. The paying court default cannot supply that missing service location.

To correct the physical venue, use **Edit service place**, enter the building and city under **Service Location**, then choose **Review recovered details**. The app updates the location wording in the Portuguese draft and PDF. For a Polícia Judiciária assignment, it retains the agency while changing the physical host. Clearing the venue asks for its building and city, with PJ-specific wording only when the source identifies PJ. Check the travel destination and kilometers separately; changing the venue does not change your travel choices.

For a notification PDF, the date comes from the interpreting appointment in the notice, rather than the notice's issue date. Check that it is the service you are claiming. If the notice also assigns written translation, the app prepares only the separate in-person interpreting request. It asks when the scope is unclear; translation-only requests remain outside this app.

If the app identifies a translation-only request, duplicate or existing draft, read the warning before continuing. Once the case and service date are clear, a known sent request or active draft is reported before asking unrelated court or travel questions. An unresolved case, conflicting date or unclear interpreting/translation scope still needs an answer first. The ordinary PDF path stays blocked until the problem is resolved. Corrections use the explicit correction workflow, not a second normal request. A blank period and “morning” for the same case/day overlap; use genuinely different periods only for separate services.

## Choose the court email

The paying court determines the email recipient, even when the interpreting took place at a police station. **Edit recipient email** opens the recipient field and **Choose a saved court email**. Select the saved court contact or enter a verified email manually, then let the app review it. The choice changes the email recipient; it does not change the paying court or service place. If they do not match, correct the request or supply a deliberate exception through the existing review rules.

If the paying authority is an exception, edit **Payment Entity** and review again. The app refreshes the addressee for that request: courts default to **Exmo. Senhor Juiz de Direito**, and Ministério Público to **Exmo. Senhor Procurador da República**. It clears the previous unchanged recipient and asks you to choose the correct court email; an email you entered along with the new payer is kept for validation. The physical venue, travel choices and saved court defaults remain unchanged. Inspect the refreshed Portuguese draft before creating its PDF.

A precise local-court match takes priority over a broad comarca contact. Conflicting equally plausible contacts pause instead of choosing whichever is listed first. Your selected recipient takes priority over unrelated footer contacts. Clearing a required photo recipient still pauses for an answer.

When a matching request was already sent, **This fee request was already sent** shows the case and service date, with the sent date and recipient when available. **No — stop** is selected by default; Escape also stops. No new PDF or Gmail draft is created, and your other cases and queue remain intact. **Yes — review details** opens the existing blocked review without permitting another submission. Changing the source or request details clears the old decision and requires a fresh review. Sent source groups cannot use the unsent-draft replacement option.

For a matched sent request, the summary shows only its recorded historical details and says **No further answers are needed**. It does not ask you to complete payment, venue or recipient fields from a blank new form. If every reviewed case in a photo was already sent, the case list remains available while new travel and replacement controls are hidden. A photo containing unfinished cases keeps their normal review controls.

When history records your confirmed paper submission, the warning says **Already submitted on paper** and blocks a repeat request in the same way. It shows only recorded submission facts; an email sent date or Gmail reference is not added for a paper submission.

New AI source reads save a small local API usage receipt with the model and token counts returned by the provider. It supports later cost checks without retaining your API key or adding another reading call. Earlier reads may have no receipt, and a receipt is not a billing invoice.

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

## Several cases in one source

The review shows **Cases found in this source** when a photo or PDF contains several case references. Use **Review case** beside each row to check its facts and questions. Your field edits and unfinished numbered answers stay with that case when you switch. An unclear case remains visible until you correct it. Each request gets its own PDF; compatible requests from the same source can share one email.

The **Travel for these source cases** controls start with **One shared trip** when the source's cases have matching visit facts. **Case that claims the shared trip** chooses the one PDF that includes travel. The first case is selected initially; the other cases retain their interpreting claims. This fits several cases handled during one journey. Choosing a travel-bearing claim on another case moves the shared trip to it. Check the previous owner's claim choice, especially if it previously claimed travel only.

Choose **Separate trips** only when separate journeys really occurred, or **No travel** when none of these requests should claim travel. Conflicting visit facts pause a shared trip until corrected; the app does not combine all requests merely because their city and day match. The shared-trip check also applies when explicitly grouped cases are prepared or recorded in separate batches. Re-uploading the same photo retains its shared-trip marker. A different or cropped photo and older history without that marker cannot establish whether travel was already claimed; check them yourself.

When every case is ready, click **Add all cases to batch** (the button includes the case count). The app checks each case again before adding the whole source. If one needs attention, it opens that case and leaves the queue unchanged. Adding cases only updates the queue; it does not create PDFs.

To include another photo, queue the current reviewed request or all its cases first, then use **Change source**. The previous queue stays in place while the next source starts with empty recovered text and capture metadata. Bulk adding a multi-case source selects separate fee-request PDFs. Check that every expected case appears in **Batch Queue**, leave **Packet mode** unchecked, run **Check batch preflight**, then use **Prepare batch package**. Review each generated PDF before any email step.

**One email per source (PDF or photo)** keeps each case's own PDF and puts the requests from that source in one email to their reviewed court recipient. Five cases in one photo produce five PDF attachments in one email; another source gets its own email. Choose **Separate emails** when needed. Different recipients or personal profiles within one source need correction or separate emails before preparation. Email grouping does not add travel to other cases.

If those cases already have drafts, enter a reason under **Replace this source's existing email**, then choose **Prepare replacement email for this source**. The app reviews every case and prepares the complete source email together. Existing drafts remain in history until a replacement is actually created and recorded. A correction cannot silently retire the other requests from an earlier grouped email.

Editing a case after queueing pauses batch preparation until you review the correction and add the updated case or source to the queue. Do not rely on an earlier green batch check after changing details. **Reset workspace** clears the whole visible queue when you want to start over.

## 5. Review the email and create a draft

After PDF preparation, use **Email draft for** to choose the photo's email or an individual request. Check every listed case, its own PDF, the court email and the email text. A packet remains one email target with its combined PDF. Changing the selected email clears its old copied handoff, returned Gmail IDs and review acknowledgement; the PDFs remain available.

**Requests included in this email** lists every member and its claim choice. Use **PDF to inspect** to read each document before checking the handoff acknowledgement.

When the app reports that Gmail is connected, review all selected PDFs and exact email details, tick the **Gmail handoff checklist**, then use **Create Gmail Draft**. This creates one unsent draft with all listed attachments; review it in Gmail and send it yourself. An error is not confirmation that a draft was created.

If Gmail created the draft but local recording failed, use **Finish local recording**. This records the existing draft without creating another. If the result is uncertain, check Gmail first and use the recovery actions to record the existing draft or explicitly confirm that none exists. **Recent Work** retains unfinished attempts after a reload or restart. Repeated clicking or preparing again cannot bypass that check. Prepared PDFs keep distinct filenames, so later corrections preserve the earlier document.

When Gmail is disconnected, or you prefer the fallback, open **Manual Draft Handoff** and click **Build handoff packet**. Check its recipient/body/attachments, then use **Copy handoff prompt**. Building or copying the packet does not create or send an email.

Check the email signature as well as the PDF signature. New default email templates use the selected personal profile's signature. Existing custom email wording stays as configured; an optional `{{signature_name}}` token makes a template follow the selected profile.

Use that exact prompt with your available Gmail draft tool or assistant to create an unsent draft. This external draft step is separate from preparing the PDF; if the draft tool is unavailable, keep the reviewed PDF and handoff packet until it is available. Direct Gmail OAuth is optional and is not required to review or prepare the document.

After the draft tool returns its response, paste it into **Paste Gmail _create_draft response**. Confirm the **Gmail handoff checklist** only after reviewing every PDF and using the exact handoff, then click **Record parsed response + prepared payload**. For a grouped email, this records every case with its own PDF so the app can warn against duplicate requests; it does not send the email.

The app checks current history again when building the handoff or recording. If an included request was sent, drafted or reserved after preparation, it pauses rather than overwriting that protection. Review the reported history before continuing; a correction still uses the explicit replacement path.

Finally, open the draft in Gmail, check the recipient and attachments again, and send it yourself when satisfied.

After sending, open **Recent Work**. With Gmail sent-status access enabled, the app checks automatically; **Sync now** checks immediately. The first setup may ask you to grant Google read permission. A verified sent email updates every fee request included in it. The app does not send anything and these checks do not use OpenAI.

The check compares the recipient, subject, complete original attachments and send time. A deleted draft alone is not proof of sending. Changed attachments, missing old evidence or uncertain matches keep duplicate protection active and display a review notice. You can still use **Gmail Draft Log → Mark manually sent**, enter the sent date and confirm after checking Gmail yourself. The automatic check runs while the local app is open; sending from your phone is detected next time you open Recent Work or click Sync now.

## Start another request

Use **Change source** to keep queued requests while clearing the current review for another photo or document. Use **Reset workspace** for a clean workspace; it clears the current review, queue and saved unfinished session without deleting stored request history, generated files or Gmail drafts. If the app reports that its server is disconnected, restart the normal launcher and reload the page before continuing.

Batch tools, detailed source evidence, reference editing and direct Gmail setup are advanced paths. They can stay closed while you complete a single ordinary request.

## Edit personal-profile distances

Profile errors and save results appear inside the open profile editor. To add a city distance, enter both the city and one-way kilometers, click **Add or update distance**, then **Save profile**. A blank distance is incomplete; enter `0` explicitly only when that is the intended value. If you edit **Advanced distance data**, use a JSON object of city names and non-negative distances, or `{}` for no saved distances. Invalid data must be corrected before saving.

## Resume unfinished work

The app automatically saves request inputs, source evidence, each case's unfinished answers, claim and shared-trip choices, and the batch queue in this browser. Manual fields are saved even before you build the request. This saved session belongs to the same browser address and app workspace; a test workspace or another data folder cannot automatically pick it up. Browser storage is separate from the app's exported backups.

After reopening or reloading, use **Resume unfinished work** near the top of the page, or **Discard saved work**. Resuming replaces any currently open request inputs. It restores inputs only: prepared PDFs, Gmail IDs, email review approval and earlier preflight results are not restored as usable actions.

Check the restored facts and selected profile, then click **Review restored work**. For several cases, review any questions, use **Add all cases to batch** to update the queue, and run **Check batch preflight** before **Prepare batch package**. The selected shared-trip owner and interpreting choices are retained; check them alongside each PDF.

File selections cannot be restored. Existing supporting files are reused only when they still exist in this workspace's upload folder. If supporting files are unavailable, the app names them and waits for **Resume without unavailable files**; this lets you recover the facts and reattach the documents before preparing. If the original source is missing, reattach it when you need to read it again. An unavailable personal profile requires you to select its intended replacement before resuming.

If automatic saving reports an error, keep the page open. Your current inputs remain visible and an earlier saved copy is retained. A damaged saved session offers an explicit discard action; it is not silently overwritten. Clearing browser storage or using a different browser/address can make that browser's saved session unavailable.

## Back up local records and pending Gmail attempts

Use **Export backup** to make a private local backup. To restore one, paste its JSON, choose **Preview backup import**, inspect the result, and provide the displayed confirmation phrase and reason before **Restore backup after preview**. The app creates a backup of the current data before restoring.

Backups include Gmail attempts that still need reconciliation. Where the original files are available and permitted, they also include the reviewed email payload and supporting PDF/image files needed to finish recording those attempts on another machine. Credentials, the complete archive of finished documents, unrelated photos and the browser's unfinished session are not included.

Restoring an older backup preserves newer local draft history and pending attempts. Conflicting identities or statuses pause the restore instead of removing duplicate protection. After a move or restart, use **Recent Work** to finish local recording of known Gmail IDs or reconcile an uncertain attempt; restoring does not create another Gmail draft or reinstate an old creation approval.

Imported historical translation receipts without a proven service date remain separate audit records through backup restore; the app does not invent an interpreting date for them. Confirmed paper-submission details are also retained.

Read warnings in export, preview and restore results. Missing, changed, unsupported or oversized files can leave an attempt protected but unable to finish local recording. Keep the original files or obtain a complete backup from the original computer. The recovery-file limits are 25 MiB per file, 100 MiB in total and 256 entries; a successful backup is not a complete document archive.
