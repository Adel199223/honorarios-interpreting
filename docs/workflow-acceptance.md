# Beginner workflow acceptance

This checklist defines evidence needed to accept the guided fee-request workflow. It is not a receipt saying those checks have passed. Prior acceptance is recorded in the [completed foundation plan](assistant/exec_plans/completed/2026-09-30_development_foundation.md). Record new results and limitations in the task's active plan and [current handoff](next-thread-handoff.md), following the [plan lifecycle](assistant/exec_plans/PLANS.md).

Use the final served build, a new isolated synthetic runtime and fictional source fixtures. Strip provider configuration from the test process. Never use real case history, personal profiles, Gmail IDs or external provider calls for this checklist.

| Step or safeguard | Required observation |
| --- | --- |
| Start | The idle page offers one clear source-upload action. Empty review panels and advanced tools do not distract from that step. |
| Upload | A synthetic notification PDF and a synthetic photo/screenshot enter the same review-first flow. No fee PDF, draft or record is created just by reviewing a source. |
| Recovered facts | The user can see what was found, inspect evidence, and correct it. Missing/uncertain fields stay visibly unresolved rather than acquiring invented values. |
| Numbered answers | Missing questions are prominent. Applying short numbered answers updates the current request and reruns ordinary review. |
| Date confirmation | A capture-date suggestion stays evidence until the service date is confirmed. Conflicting dates stop preparation; choosing another date or remaining unsure is possible. |
| Invalid work and duplicates | Translation/word-count sources, missing required information, drafted/sent duplicates and active drafts block the normal creation path with an understandable next action. |
| Ready request | The user reaches the Portuguese draft preview through the visible next-step action. PDF creation still requires the current valid review/preflight. |
| PDF | Open/render the generated synthetic PDF and inspect text, recipient/entity wording, dates, amounts/travel wording and page layout. A successful file write or text assertion alone is insufficient. |
| Manual handoff | The current prepared PDF leads to a handoff packet containing the reviewed recipient/body/attachments. Building/copying it does not contact Gmail or create local draft records. |
| Local recording | Fake draft IDs are accepted only in an isolated test and with current prepared-review binding plus the review acknowledgement. Duplicate protection is updated for every underlying request. |
| Stale state | Editing source/intake/queue/attachments after preparation clears old previews/handoff/record helpers. Reusing stale preparation is rejected by the server too. |
| Reset and connectivity | Reset clears visible client state without removing stored history. A disconnected server visibly blocks server-writing actions. |
| Usability | Main actions remain legible at the reviewed desktop/mobile widths; keyboard focus reaches upload, answer and preview actions without hidden controls trapping it. |

Use focused public tests for the changed behavior, a real browser for the visible sequence, and a rendered PDF for document acceptance. A missing browser/file-input/rendering capability is a recorded limitation, not permission to substitute private data or claim that another kind of check proved the same result.

Run [Full validation](validation.md) on the final integrated build before publication is proposed. Actual real-document/provider use and future main-app integration remain separately scoped acceptance.
