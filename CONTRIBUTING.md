# Contributing

Use synthetic fixtures only. Do not commit real case numbers, court email addresses, Gmail draft IDs, generated PDFs, source screenshots, IBANs, addresses, or local API keys.

Before opening a pull request, run:

```powershell
python -m unittest discover tests
python scripts/public_release_gate.py --no-require-git --json
```

The Gmail workflow is draft-only. Do not add UI, API, scripts, or tests that send email automatically.
