# Image Metadata Date Rule

When the user provides screenshots/photos rather than a clean PDF, inspect both the document text and the visible gallery/file metadata.

## Rule

Use this priority for the service date:

1. User-confirmed service date.
2. Visible photo/image metadata date.
3. Explicit service wording in the document, such as `serviço prestado no dia`.

If the image metadata date and a document date conflict, stop and ask the user which one is the service date. After the user answers, set `service_date_source` to `user_confirmed` or `user_confirmed_exception`.

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

The generator treats `service_date` as highest priority only when the conflict is user-confirmed. Otherwise it stops on conflicting dates. If `service_date` is absent, it falls back to `photo_metadata_date`.

Duplicate checks use the same effective service date.

Use `user_confirmed_exception` when the user chooses a non-default date, such as a printed document timestamp over the visible image metadata date. The intake `notes` must explain the exception so future agents can audit the choice quickly.

## Example

If a document says `2026-02-12 12:30` but the visible image metadata says `Feb 16`, tell the user there is a conflict and ask which date to use. If the user confirms `2026-02-12`, record it as `service_date` with `service_date_source: user_confirmed_exception`.
