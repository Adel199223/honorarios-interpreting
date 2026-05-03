# Duplicate Check

Before creating a new interpreting honorários PDF, compare the new paper against `data/duplicate-index.json`.

This file is the single duplicate-warning source for both sent and drafted requests. Records with `status: sent` or `status: drafted` block future generation. Older records without `status` are treated as `sent`. Records marked `superseded`, `trashed`, or `not_found` stay auditable but do not block.

If the same `case_number` and the same `service_date` already exist with a blocking status, stop before generating a document and tell the user it is probably a duplicate. For repeated same-day services, compare `service_period_label` as well: exact same case/date/period blocks, while morning and afternoon can coexist.

Duplicate checks use the same effective service date as PDF generation. If `service_date` and `photo_metadata_date` conflict and the conflict is not user-confirmed, the duplicate check must fail with an input error instead of reporting "no duplicate found."

After a Gmail draft is created, record it with `scripts/record_gmail_draft.py`. That command also upserts a `status: drafted` duplicate-index record immediately. When the draft is manually sent, update the same duplicate-index record to `status: sent` and add `sent_date`.

## Current Duplicate Index

The index includes historical sent requests and active drafted requests. Read the JSON file directly for the current full list:

```text
data/duplicate-index.json
```

## Command

Check an intake file:

```powershell
python scripts/check_duplicate.py examples/intake.example.json
```

Check a case/date pair:

```powershell
python scripts/check_duplicate.py --case-number 398/24.5T8BJA --service-date 2026-02-05
```

Exit codes:

- `0`: no duplicate found.
- `2`: missing or invalid input.
- `3`: duplicate found.
