# Development guide

## Requirements

- Python 3.11 or newer
- `uv` for reproducible dependency management
- Git
- PostgreSQL will be required when Phase 1 persistence begins

## Setup

```powershell
uv sync --extra dev
Copy-Item .env.example .env
```

Set `GEMINI_API_KEY` only in the local `.env` file. Do not paste it into source files, tests,
logs, issues, or commits.

## Local commands

```powershell
uv run uvicorn unilog_product_intelligence.api:app --reload
uv run pytest
uv run ruff format .
uv run ruff check .
uv run mypy src
```

The Phase 0 Gemini adapter intentionally raises `NotImplementedError` for generation. This is a
guardrail: tests can prove no network call happens before the Phase 4 integration is designed.

## Data handling

Do not add invented product records. Runtime data belongs outside the repository unless the
source is explicitly approved and its licensing/storage status is documented. Before Phase 1,
record the exact files discovered and their headers/checksums without copying unavailable files.

## Quality bar

Changes should include typed code, focused tests, documentation updates, deterministic validation,
and a clean Git status. New external integrations need an ADR or an update to an existing ADR.

