# Development environment

Use the project's locked environment so development and automated checks exercise the same package versions. The supported daily workflow runs from this source checkout.

## Pinned tools and dependencies

| Tool | Development pin | Purpose |
| --- | --- | --- |
| Python | `3.11.9` | Project environment and validation. |
| uv | `0.12.20` | Locked dependency installation and export. |
| Node.js | `24.14.0` | JavaScript syntax checks and optional browser tooling. |

The interpreter declaration, `pyproject.toml` and `uv.lock` define the reproducible environment. The initial lock preserves the fee app's observed runtime package versions; it does not upgrade the previous global Python environment. `requirements.txt` is a generated locked export, not an independently edited dependency list.

For a dependency change, update the project declaration deliberately, resolve the lock in an isolated environment, regenerate the export and run the full validation. Routine setup must use the existing lock; do not run an unlocked install or blanket upgrade.

## Windows setup

Run from the project root with the pinned tools available:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_dev_env.ps1
.\.venv311\Scripts\python.exe scripts/check_dev_environment.py --json
```

The setup helper creates the project `.venv311` environment. It checks pinned prerequisites and standard-library integrity before changing an environment. An existing environment must already pass the read-only check; a mismatch is preserved and refused. No automatic Python download or global package upgrade occurs. A different disposable environment name may be supplied with `-VenvName .venv311-check`, or a complete existing pinned interpreter with `-PythonExecutable <path>`.

The initial September check found the old Python 3.11 installation missing `xml.dom.minidom`. A separate complete uv-managed Python 3.11.9 was provisioned and verified; the old Python/global environment was left intact. On another PC, provision the exact interpreter deliberately before setup. See [uv's lock and sync documentation](https://docs.astral.sh/uv/concepts/projects/sync/) for the locked installation behavior.

Start the source-checkout app:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_dev.ps1
```

The helper uses `http://127.0.0.1:8878/` by default so it can coexist with the main app and its Gmail bridge. It does not change the application's historical direct-launch default of `8765`. Do not terminate an unrelated server to free a port.

For a disposable review session, choose a new runtime directory and use:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_dev.ps1 -RuntimeRoot .tmp-test/review-runtime -Synthetic
```

Synthetic mode is for tests and review, not real requests. The helper requires a new or empty regular directory and refuses linked or populated runtime paths, because fixture initialization writes records. Relative paths resolve against this checkout. Private data, provider credentials and generated real documents do not belong in that runtime.

## Cross-platform equivalent

With the pinned Python/uv/Node tools installed, the installation operation is `uv sync --locked --extra dev`. Select the same `.venv311` project environment explicitly. For a POSIX shell:

```sh
UV_PROJECT_ENVIRONMENT=.venv311 uv sync --locked --extra dev
.venv311/bin/python scripts/check_dev_environment.py --json
.venv311/bin/python scripts/run_portable_tests.py
```

Use the resulting project interpreter for all commands. The environment checker enforces a checkout-local directory whose name starts with `.venv`; the normal launcher and validator use `.venv311`. Do not invoke an unrelated global interpreter. See the checked-in CI configuration for its full portable command sequence.

## Optional capabilities

PDF page rendering needs `pdftoppm`; browser click-through needs the documented browser adapter or Playwright tooling. A missing optional capability must be reported as a blocker for that check. API-level isolated smoke remains useful without a browser.

AI, Google Photos and direct Gmail OAuth are optional, private local configuration. This setup does not configure credentials or make provider calls. If an existing OAuth configuration uses the historical port, its callback and chosen launch port must agree; changing that provider configuration is a separate reviewed operation. Manual Draft Handoff remains available without Gmail OAuth.

## Distribution scope

The wheel check builds and installs a package from the locked environment, then exercises a synthetic workflow outside the checkout using an explicit runtime root. It verifies packaged helpers/templates/assets are usable. Daily private use of an installed distribution with default runtime paths is not yet an accepted deployment mode; use the source checkout until that configuration is implemented and reviewed.

Continue with the [validation guide](validation.md). Current completed checks and limitations belong in [the handoff](next-thread-handoff.md).
