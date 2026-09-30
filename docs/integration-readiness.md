# Future LegalPDF integration readiness

Developing Honorários separately keeps its interpreting fee-request rules and private runtime data isolated while the workflow matures. The future integration should use the existing adapter boundary so the main app can present the workflow without duplicating its business rules.

## Authoritative boundary

The existing [LegalPDF adapter contract](legalpdf-adapter-contract.md) describes the versioned machine-readable `/api/integration/adapter-contract` endpoint, endpoint sequence, review freshness binding and Gmail restrictions. The reusable caller is `scripts/legalpdf_adapter_caller.py`.

Honorários owns PDF generation, profiles, recipient/service rules, duplicate protection, prepared artifacts, draft payload validation and local draft records. LegalPDF Translate remains read-only from this app. The future caller must use the APIs and current review tokens, not edit either application's private JSON files directly or import a parallel implementation.

Manual Draft Handoff is the required draft-only boundary. Optional direct OAuth draft creation is separate; it must not become a prerequisite for the adapter sequence or add Gmail send/trash/delete/search behavior.

## Preparation and acceptance checklist

| Area | Required evidence | Current preparation scope |
| --- | --- | --- |
| Reproducible source environment | Locked setup, pinned tool checks and full validation in isolation. | Added by September preparation; actual results recorded in the handoff. |
| Packaged code/resources | Real wheel installation and synthetic flow outside the checkout with explicit runtime root. | Included in full validation; default installed private-runtime setup remains deferred. |
| Contract compatibility | Check accepted version, fields/endpoint sequence, nested draft-only boundary and stale-review rejection. | Isolated smoke covers the current `2026-05-10.optional-gmail-boundary.v4` fields and guards. Explicit version/method negotiation belongs in the future production caller. |
| Data ownership | Explicit runtime paths, private overlays, separate logs/profiles and reviewed mapping/import policies. | Existing ownership guards; no private imports during preparation. |
| Concurrent local use | Identify server ownership and use separate ports. | Development helper defaults to `8878`; historical direct-launch behavior is preserved. |
| Main-app user flow | A real LegalPDF caller plus UI, process lifecycle, errors and duplicate/correction explanations. | Future implementation and review. |
| Real document/Gmail acceptance | User-reviewed PDFs, current recipient checks and explicitly authorized draft-only operations. | Deferred; synthetic tests do not replace this acceptance. |
| Publication/deployment | Reviewed changes, required checks and explicit publication scope. | Separate operation; preparation does not publish. |

## Next integration work

After the standalone workflow is stable in daily use, implement the main app's caller against the documented APIs. Decide process ownership, startup/shutdown, selected runtime root, port discovery, profile/reference mapping, error handling and the user's review handoff before enabling production writes.

Keep a read-only readiness probe available. The full caller sequence must continue to refuse a normal private runtime during synthetic acceptance. Profile import/apply/restore features remain explicit, backup-first operations and are not part of ordinary environment setup.

Follow [development setup](development-environment.md), [validation](validation.md) and [current handoff](next-thread-handoff.md) for preparation results. The older roadmap documents implemented features and historical next-stage ideas; it does not authorize live operations or indicate that main-app integration has happened.
