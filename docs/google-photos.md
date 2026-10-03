# Google Photos and original-photo metadata

The app can read capture metadata directly from an original image and can import one user-selected photo through Google Photos Picker. The [completed readiness plan](assistant/exec_plans/completed/2026-10-02_photos_metadata_readiness.md) and [handoff](next-thread-handoff.md) record actual authorization, selection and download, normal browser/PDF acceptance, and passing final Full checks in both the candidate and saved app. Direct Picker import recovered the tested photo's original capture date; automatic location remains limited as described below.

## Choose the source

The **Google Photos** top-bar button opens the existing source options without clearing the current request or queue. **Connect Google Photos OAuth** starts consent in Google; **Open Google Photos Picker** starts a selection. Choose exactly one image, finish selecting, then return to **Import Picker selection**. **Check Picker selection** can confirm readiness first. Multiple selections and videos are rejected rather than silently choosing a different source.

The local alternative is to download the original image yourself and choose it under **Google Photos selected-photo import**, or use the ordinary photo upload. An optional text box accepts visible photo details, such as the capture city. Importing only starts source review; it does not prepare a PDF or Gmail draft. Saved photo defaults, per-case review, duplicate warnings, recipient checks and the usual preparation acknowledgement still apply.

Google directs apps that need user-selected library photos to Picker; the Library API's general library access was restricted in March 2025. This app does not scan the whole Photos library. [Google's API changes](https://developers.google.com/photos/support/updates).

## Default Camera chooser

When an original phone Camera folder has been configured locally, **Add source file** opens that folder inside the app automatically. Search by a filename or date such as `2026-10-02`, select one photo, then click **Review source**. **Choose another file** retains the normal browser upload for PDFs and other local sources. Without a saved Camera setting, the original file input remains the default.

The private `config/source-import.local.json` accepts one absolute `camera_folder` path. It is resolved beside the runtime's AI configuration, so isolated test runtimes do not inherit the real phone folder. No HTTP route can change the folder. Startup checks configuration only; listing reads metadata for at most 5,000 immediate folder entries, 50 per page. The chooser then loads visible photo previews locally, a few at a time, into a responsive thumbnail grid. Previews respect EXIF orientation, show the whole image and omit embedded metadata. A bounded memory cache avoids repeated decoding while the source remains unchanged; no thumbnail files are saved. Search uses filenames, not EXIF dates. Choosing a listed JPG/JPEG/PNG still imports its unchanged original, up to 25 MiB, rather than the reduced preview. HEIC/HEIF is not supported by this chooser. The phone must remain connected; missing/changed files require refreshing or another selection.

The photo tiles retain their filenames and remain selectable if a preview cannot load. A changed-file preview explains that its folder listing is stale. **Refresh photos** rereads the current search/page and obtains fresh fingerprints before retrying previews; it does not select, upload or review a file. The control is disabled during selection/listing and when the runtime is unavailable. Browsing previews makes no AI/provider call. Opening or cancelling the chooser preserves work; changing page/search or closing it cancels obsolete preview work. Choosing a replacement clears old prepared artifacts and requires source review, including multi-case replacement checks. Late reads cannot replace a newer selection. Selection alone does not run AI, create a fee PDF, call Gmail or update case history. The existing **Review source** action keeps the app's configured source-reading behavior and all ordinary review rules.

## Original Android photos through Windows File Explorer

On a supported, connected Android phone, Windows **Manage mobile devices** can expose phone storage in File Explorer after the user grants the phone's file-access permission and enables **Show mobile device in File Explorer**. Choose the original file in the phone's **Internal storage > DCIM > Camera** folder through the app's **Add source file** control, then review the source normally. Pinning that Camera folder in Quick access makes later selection easier. Keep the phone connected while Windows retrieves an online file. See [Microsoft's File Explorer setup instructions](https://support.microsoft.com/en-us/windows/experience/fileexplorer/setting-up-and-using-your-phone-in-file-explorer).

A 2 October device-specific comparison found that **Phone Link > Photos > Save as** produced a smaller copy retaining the capture date but losing GPS. Reading the same image directly from the phone's Camera folder retained both date and GPS, and the normal app upload read both with AI disabled. Prefer the verified original-file route on that setup; this result does not establish that every Phone Link version strips GPS. Private device paths and receipts remain in ignored local setup evidence.

Original GPS can supply a city automatically when it falls inside an optional, locally configured verified area. Review labels this **GPS matched a verified local area**, separately from embedded city metadata. There is no geocoder or nearest-city fallback, and GPS never establishes the physical service building. Missing, conflicting or ambiguous city evidence still produces one numbered capture-city question. Its answer is bound to that photo and applies the verified saved court/contact, missing-venue and travel defaults where applicable without another AI read. Unknown contacts, named venues, manual exceptions and other unresolved questions still require review. Importing a photo does not establish attendance, create a fee request or mark a case complete. See [verified GPS area configuration](source-quality.md#saved-photo-defaults).

## Capture date and location

| Available evidence | What the app does |
| --- | --- |
| Original EXIF capture timestamp | Keeps its local calendar day and records the timestamp's provenance. A valid recorded UTC offset is retained separately. |
| Picker creation timestamp with original EXIF | Keeps original capture-day evidence and exposes any conflict with the configured timezone conversion. |
| Picker timestamp without original EXIF | Converts it only using an explicit saved capture timezone; otherwise the local date stays unresolved. |
| Embedded city explicitly marked as the capture location | A unique city can feed the saved capture-city court rule. Conflicting cities require review. |
| GPS coordinates inside one configured verified city area | Shows a derived city candidate and applies saved city defaults only when other capture-city evidence agrees. |
| GPS without a matching verified area | Displays coordinates as evidence and asks for missing city information; no nearest-city guess. |
| Image modification date, location shown in the photograph, or generic legacy City tag | Does not establish the capture day or capture city. |

Picker's `createTime` describes media creation, not upload, and is returned as an RFC 3339 instant. A UTC calendar day can differ from the local capture day, particularly near midnight. [Google's media-item reference](https://developers.google.com/photos/picker/reference/rest/v1/mediaItems).

Google's REST image download parameter `=d` retains EXIF except location metadata. Its media-item schema does not provide GPS or a capture-city field. Consequently, direct Picker import cannot promise automatic location; supply the city or use an original local file containing explicit capture-location metadata. The app has no automatic geocoding. [Google's download documentation](https://developers.google.com/photos/picker/guides/media-items#image-base-urls).

The saved capture-day-as-service-day policy remains a user preference, separate from camera evidence. Review the actual service day and venue before requesting payment. Photos taken in another timezone need the correct timezone or an explicit date answer.

## Local configuration

OAuth client settings and tokens remain in ignored local configuration. The callback address must match the actual local app port. Use the existing setup instructions and `config/google-photos.example.json` as a template; preserve any existing private settings. Google Photos has its own Picker authorization, separate from Gmail draft authorization. A status saying authorization is saved does not prove current provider access; opening Picker exercises that connection.

The optional timezone is a photo preference in ignored `config/photo-defaults.local.json`, not an OAuth field. Merge the key into the existing preferences, for example:

```json
"capture_timezone": "Europe/Lisbon"
```

Choose the IANA timezone that actually applies to the photos being imported. The app uses timezone rules, including historical daylight saving, and never substitutes the host computer's current timezone. The locked `tzdata` dependency supplies those rules on Windows. Missing, invalid or unavailable timezone rules leave a timestamp-only date unresolved; original EXIF local-date evidence remains usable.

Provider failures distinguish reconnecting consent, enabling Picker API/access, expired sessions, incomplete selections and retryable network errors. Reopen Picker after an expired selection. Review responses and logs must keep tokens, OAuth secrets and download URLs private. Tests use synthetic metadata and offline provider transports; their success does not establish a live account connection.
