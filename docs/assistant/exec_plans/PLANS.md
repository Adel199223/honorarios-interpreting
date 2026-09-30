# Small plan lifecycle

Use a plan for a substantial change that crosses several files, alters a user workflow, or needs staged acceptance. A small isolated correction can use the handoff and change description instead.

## Create and maintain

Create one Markdown file under `active/` named `YYYY-MM-DD_scope.md`. Include the goal and authorized scope, published base and local-work provenance, contracts to preserve, implementation steps, acceptance evidence, risks, rollback/beforeimages, and dated progress.

Keep the plan current while working. Record actual outcomes, failed attempts, skipped capabilities and remaining work. A checkpoint commit or passing unit suite is progress; it is not proof of browser, PDF or live-provider acceptance.

The [development foundation plan](completed/2026-09-30_development_foundation.md) is complete locally. Its authorized publication is tracked in [PR #59](https://github.com/Adel199223/honorarios-interpreting/pull/59). Create the next active plan when a substantial new development task starts.

## Complete and preserve

Move a plan to `completed/` only when the authorized objective and required checks are complete. Preserve its implementation history and limitations, then update the current handoff and documentation map to point to the next work. Local completion and publication are separate statuses; a completed local plan can still describe an unpublished change.

If work pauses or cannot complete, retain the active plan with a precise next action and blocking condition. Do not move it to completed merely to tidy the folder, and do not invent stage approval requirements for already authorized work.

Preserve exact beforeimages for replaced current guidance and saved local work in ignored task evidence. Plans must be portable and public-safe: use repository-relative paths, fictional fixtures and secret-free summaries, never private records or machine-specific account paths.

Use [the workflow acceptance checklist](../../workflow-acceptance.md) and [validation guide](../../validation.md) when the interpreting workflow changes.
