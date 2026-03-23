# Open Agentic Memory Release Notes

## Public Release Readiness

This release prepares Open Agentic Memory for public open-source use with a focus on safety, clarity, and first-run polish.

## Highlights

- Removed risky secret persistence from generated config output and shifted the project toward `.env` or OpenClaw-managed auth.
- Added a lightweight automated regression suite for config loading, auth resolution, and local memory-store smoke coverage.
- Tightened public-facing documentation so supported backends and integration modes match the shipped implementation.
- Added baseline project surfaces expected from a polished public repository: CI, security guidance, contributor guidance, and structured issue intake.
- Removed external Google Fonts dependencies from the shipped UI surfaces so the repo is more self-contained.
- Replaced deprecated FastAPI startup and shutdown hooks with a lifespan-based app lifecycle.

## Security And Hardening

- No committed secrets, OAuth verifier artifacts, private keys, email addresses, or machine-local paths were found in the tracked tree or reachable git history during the release audit.
- Generated `config.yaml` no longer stores resolved API keys or gateway tokens by default.
- Runtime gateway resolution still works by falling back to `.env` and detected OpenClaw gateway auth.
- The legal owner string now uses `WCDispatch LLC`.

## Developer Experience

- Added `tests/test_config.py` and `tests/test_runtime.py`.
- Added GitHub Actions CI to run compile checks, shell syntax, plugin syntax checks, and the Python test suite.
- Added `SECURITY.md`.
- Added `CONTRIBUTING.md`.
- Added GitHub issue templates for bug reports and feature requests.

## Product Polish

- Added explicit Python and dependency prerequisites to the README.
- Removed self-install behavior from `serve_chat.py`; startup now fails clearly with setup instructions instead of mutating the environment.
- Updated the shipped HTML surfaces to use local font stacks instead of remote font imports.
- Migrated the FastAPI app to a lifespan-based startup and shutdown flow.

## Verification

The release state has been validated with:

```bash
python3 -m py_compile serve_chat.py openclaw_setup.py src/agentic_memory/config.py src/agentic_memory/runtime.py
bash -n setup.sh
node --check plugins/recall-tools/index.js
node --check plugins/observer-tools/index.js
.venv/bin/python -m unittest discover -s tests -v
```

All checks passed during the final release-prep pass.
