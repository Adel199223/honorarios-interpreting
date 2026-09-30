# Image Metadata Date Rule

When the user provides screenshots/photos rather than a clean PDF, inspect both the document text and the visible gallery/file metadata.

## Rule

Use this priority for the service date:

1. User-confirmed service date.
2. One unambiguous capture day when the saved photo-date default is enabled.
3. Explicit service wording in the document, such as `serviço prestado no dia`, when no saved photo-date default applies.

With the saved photo-date default enabled, apply the capture day without repeated confirmation and retain a different printed date as evidence. Without it, uploaded capture-only dates and unresolved document/capture conflicts require the user's choice. Missing or competing capture dates still ask. After an explicit answer, set `service_date_source` to `user_confirmed` or `user_confirmed_exception`.

Do not use these as service dates unless confirmed:

- Printed appointment timestamps.
- Procedural document timestamps.
- Closing/signature dates.
- File upload dates.

## Fields

Use:

```json
{
  "service_date": "2026-02-12",
  "photo_metadata_date": "2026-02-16",
  "service_date_source": "user_confirmed_exception",
  "source_document_timestamp": "2026-02-12 12:30"
}
```

Photo intake with the saved default sets both `service_date` and `photo_metadata_date` to the chosen capture day and labels `service_date_source` as `photo_metadata`. A manual exception can replace `service_date`. The generator stops on unresolved conflicts, and an uploaded capture-only date cannot bypass a required confirmation. Deliberately clearing the selected date keeps it unresolved through review.

Duplicate checks use the same effective service date.

Use `user_confirmed_exception` when the user chooses a non-default date, such as a printed document timestamp over the visible image metadata date. The intake `notes` must explain the exception so future agents can audit the choice quickly.

## Example

If a document says `2026-02-12 12:30` but the photo's capture metadata says `2026-02-16`, the saved photo-date default selects `2026-02-16`. Without that preference, ask which date to use. If the user explicitly chooses `2026-02-12`, record it as `service_date` with `service_date_source: user_confirmed_exception`.
