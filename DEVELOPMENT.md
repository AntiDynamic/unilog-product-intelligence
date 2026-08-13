# Development guide

## Requirements

- Python 3.11 or newer
- `uv` for reproducible dependency management
- Git
- PostgreSQL is the target persistence engine; the Phase 1 DDL is in `database/schema.sql`

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
uv run unilog-inspect-data --data-root /mnt/data
```

`unilog-inspect-data` writes `docs/research/data-inventory.json` by default. It computes row and
column counts, nulls, placeholders, unique values, duplicate rows, representative values, data
types, worksheet names, merged ranges, and leading rows from files that actually exist. Missing
files are recorded as unavailable without fabricated metrics.

`unilog-validate-delivery` consumes one generated JSON delivery schema and reports missing,
unexpected, duplicate, reordered, and wrong-width data.

The Phase 0 Gemini adapter intentionally raises `NotImplementedError` for generation. This is a
guardrail: tests can prove no network call happens before the Phase 4 integration is designed.

## Data handling

Do not add invented product records. Runtime data belongs outside the repository unless the
source is explicitly approved and its licensing/storage status is documented. Record the exact
files discovered, headers, worksheets, checksums, and quality metrics without copying unavailable
files. Raw values are retained in ingestion results and PostgreSQL JSONB columns; normalization
never silently destroys source values.

## Quality bar

Changes should include typed code, focused tests, documentation updates, deterministic validation,
and a clean Git status. New external integrations need an ADR or an update to an existing ADR.