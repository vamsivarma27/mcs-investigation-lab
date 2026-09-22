# Contributing

Thanks for helping improve MCS Investigation Lab.

## Development setup

```bash
git clone https://github.com/vamsivarma27/mcs-investigation-lab.git
cd mcs-investigation-lab
uv sync --extra dev
MODEL_PROVIDER=mock uv run uvicorn lab.api:app --host 127.0.0.1 --port 8765
```

Use mock mode for development and tests. Never commit `.env`, API keys, databases, model
outputs containing private data, or real investigation material.

## Before opening a pull request

```bash
uv run ruff check .
uv run pytest -q
node --check lab/static/app.js
uv run python -m lab.validate_case
```

Keep pull requests focused. Explain the user-facing behavior, security impact, test evidence,
and any format or migration change. New tools must use strict input schemas, be added to a
named skill, enforce run and role ownership, and produce audit events. New cases must keep the
public case separate from its sealed answer vault and pass the case validator.

## Good first contributions

- New agent templates composed from existing skills
- New validated cases and difficulty calibrations
- Provider adapters that preserve typed tool calls
- Evaluation and visualization improvements
- Accessibility, documentation, and test coverage

By participating, you agree to follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
