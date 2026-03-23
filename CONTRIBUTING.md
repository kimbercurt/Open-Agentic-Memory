# Contributing

Thanks for contributing to Open Agentic Memory.

## Development Setup

Use Python 3.9 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

For the guided local setup flow:

```bash
bash setup.sh
```

For the manual runtime path:

```bash
cp config.example.yaml config.yaml
.venv/bin/python serve_chat.py --init-only
.venv/bin/python serve_chat.py
```

## Before Opening a PR

Run the same baseline checks that CI runs:

```bash
python3 -m py_compile serve_chat.py openclaw_setup.py src/agentic_memory/config.py src/agentic_memory/runtime.py
bash -n setup.sh
node --check plugins/recall-tools/index.js
node --check plugins/observer-tools/index.js
.venv/bin/python -m unittest discover -s tests -v
```

## Repo Hygiene

- Do not commit `config.yaml`, `.env`, databases, or generated memory data.
- Keep examples and README behavior aligned with the shipped implementation.
- Prefer small, focused PRs with a short explanation of user-facing impact.

## Security

If you believe you found a vulnerability, please follow the instructions in `SECURITY.md` instead of opening a public issue.
