# Honorários development and integration preparation

## Goal and scope

Prepare LegalPDF Honorários for dependable separate development and eventual integration with LegalPDF Translate. Implement a locked Python environment, explicit launch/validation tools, reproducible CI, distribution checks and coherent setup/architecture/continuity documentation. Preserve draft-only, duplicate, recipient and review-freshness safeguards and existing UI work. Actual main-app wiring, credentials, personal-data import, Gmail/provider calls, public publication, package upgrades and moving/renaming the saved project are outside scope.

## Provenance

- Original saved project: the existing Honorários checkout.
- Original branch: `codex/beginner-guided-intake-ux`; base `a0ef9e1`.
- Preparation branch/worktree: `codex/integration-readiness-20260930`, `.worktrees/integration-readiness`.
- Packaging worktree: `.worktrees/readiness-packaging`, same HEAD and pending-work patch.
- Both start with all 15 existing tracked modifications. Exact byte beforeimages and original patch are retained in ignored `.tmp-test/integration-readiness-20260930`.
- Target: apply only reviewed preparation deltas to the original checkout, preserving its branch and pending UI work. No main-app files change.

## Decisions and contracts

- Use this PC's existing Python 3.11.9, uv 0.12.20 and Node 24.14.0; no workstation reinstallation is needed.
- Seed the app lock with observed fee-app runtime package versions from global Python 3.14.4. Create a separate 3.11 environment; leave that old interpreter/packages intact. This makes the supported development Python match the main app without merging dependency sets.
- Preserve historical server/OAuth defaults. New coexistence launcher explicitly selects port 8878; isolated smoke chooses an available port. LegalPDF's bridge remains 8765 and its UI 8877.
- Adapter contract remains `2026-05-10.optional-gmail-boundary.v4`. Live readiness probing is read-only; complete caller sequences remain synthetic-only. No route, payload, selection, Gmail or freshness contract changes.
- Public source fixtures differ from ignored local regression fixtures. Validation defaults must use tracked synthetic tests rather than quietly depending on local private fixtures.

## Implementation

1. Add exact Python/Node/uv pins, dependency lock and locked requirements export; ignore environment/build outputs.
2. Add checked setup, environment verification, coexistence launcher and validation wrappers. Existing environments must be checked before mutation; failed first creation is retained for diagnosis.
3. Make blocked runtime-doctor checks return nonzero, with regression coverage.
4. Include shared scripts and generator template in the wheel; verify outside the checkout with an isolated synthetic runtime.
5. Freeze Windows CI and the optional Linux CircleCI path and exercise unit tests and isolated adapter/API smoke.
6. Add concise development/architecture/validation/integration readiness front doors; update README, CONTRIBUTING and current handoff. Preserve documentation beforeimages; retain historical roadmaps.
7. Validate in isolation, apply preparation files with guarded original hashes, create/check the original checkout's dedicated environment and record outcomes.

## Acceptance and fallback

- Fresh Python 3.11.9 environment reconstructs from unchanged lock; runtime package versions match the observed fee-app baseline.
- Public synthetic unit suite, JavaScript syntax, isolated source/proof/adapter/fake-Gmail smoke and installed-wheel smoke pass without real data/provider access.
- Launch helper rejects occupied port and supports explicit isolated runtime paths.
- Existing UI/source modifications and private overlays remain preserved; exact beforeimages support rollback of touched guidance.
- Final handoff distinguishes local validated/applied state from unpublished source, optional browser review and future production integration.

## Progress

- Audit and source isolation complete. Existing integration safety boundary is substantial; current setup floats interpreter/packages and public CI lacks reconstruction/adapter checks.
- Initial local preparation was completed and applied to the original saved checkout, preserving its branch and pre-existing interface work. That phase performed no commit, push, merge, main-app change or provider operation. The user then separately approved the publication-only branch and merge after successful GitHub checks.

- Publication preflight (2026-09-30): the preparation-only delta was reconstructed on fresh `origin/main` (`a0ef9e1`) in `codex/fee-environment-preparation-20260930`. Its independent locked setup and Full validation passed 89 portable tests and four isolated workflow smokes. This scope excludes the earlier beginner-interface edits and local/private files. The earlier 91-test runs include that separate interface work. The user subsequently approved publication of this scope and merge after GitHub checks pass. The update is published in [PR #58](https://github.com/Adel199223/honorarios-interpreting/pull/58). Hosted Windows/GitHub Full validation passed [run 186](https://github.com/Adel199223/honorarios-interpreting/actions/runs/36726038688) at `dc0d3af`. The original preparation receipt remains evidence for the initial local application.

## Executed validation and qualifications

- Pinned Python/uv/Node checks, application imports, lock/export consistency and package compatibility pass. Independent reconstruction installed 37 distributions; the 29 observed fee runtime package versions are unchanged.
- The old installed Python lacked `xml.dom.minidom`. A separate complete uv-managed Python 3.11.9 now backs only the new fee environments. Its installation initially reported a minor-version-link error; direct stdlib imports and uv discovery verified the complete result. Old environments remain intact.
- Isolated authoring Full passed 91 public synthetic tests, including actual offline installed-wheel verification, and four isolated source-upload/proof/adapter/fake-Gmail smokes. Saved-checkout Full independently passed the same suite/workflows after application. Counts are repeated runs, not additive unique coverage.
- Initial failures are retained: startup documentation expectation, diagnostics timeouts from scanning environments/worktrees, and newline-only export/template assertions during original-checkout application. Fixes distinguish preserved legacy defaults, prune traversal while retaining release blockers, and compare semantic text across Windows newlines.
- Portable tests run from a temporary allowlisted source checkout, excluding private overlays, unlisted local tests and provider environment values. Launch helper safety tests reject populated synthetic paths and occupied ports.
- The installed wheel includes shared scripts/template/assets and runs from outside the checkout with explicit synthetic runtime paths. Installed default private-runtime configuration and repository-specific diagnostic parity are not accepted deployment modes.
- Documentation routing/links, JavaScript syntax, whitespace and preparation-content privacy checks pass. Current guides/handoff and a small machine routing map are synchronized. Exact beforeimages, original work patch, environment evidence and operation logs are retained in ignored local evidence.
- Hosted Windows/GitHub CI subsequently passed during the authorized publication phase. CircleCI/Linux, optional browser click-through and real documents/providers remain unexecuted. Production main-app orchestration remains separate work. Publication excludes prior interface edits and private/local files; only the reviewed 37 preparation files are included.
