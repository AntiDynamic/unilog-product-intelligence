# UniLog Product Intelligence

Evidence-constrained product intelligence for industrial commerce.

This repository is the Phase 0 engineering foundation for the UniHack 2026 challenge. The
planned system transforms limited, messy product information into reliable, standardized,
commerce-ready intelligence through:

```text
UNDERSTAND → ENRICH → NORMALIZE → VALIDATE → COMPOSE → DELIVER
```

AI may propose facts. Evidence, controlled vocabularies, business rules, and validators decide
whether a fact becomes final product data.

## Current status

Phase 0 is complete in this repository:

- typed Python package with a FastAPI application factory and operational health endpoint;
- provider-neutral `LLMProvider` port with configuration-only Gemini and future local adapters;
- initial `ProductTruth` domain boundary with provenance and evidence fields;
- secure environment contract for `GEMINI_API_KEY`;
- pytest, Ruff, mypy, and GitHub Actions configuration;
- architecture, development, ADR, research, and phase-roadmap documentation.

No product records, fabricated examples, Gemini calls, enrichment pipeline, database schema,
frontend, or mock product responses have been added.

## Quick start

```powershell
uv sync --extra dev
uv run uvicorn unilog_product_intelligence.api:app --reload
```

The local API health check is `http://127.0.0.1:8000/health`.

Copy `.env.example` to `.env` and provide `GEMINI_API_KEY` locally when model integration is
implemented. `.env` is ignored by Git and must never be committed.

## Validation

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

## Scope and next step

The next implementation increment is Phase 1: inspect the real supplied files, establish
ingestion contracts, load official master/reference data when present, normalize known
placeholders, and create real database structures. See [the phase roadmap](docs/phases/roadmap.md)
and [the development guide](DEVELOPMENT.md).

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Development](DEVELOPMENT.md)
- [Phase 0 record](docs/phases/phase-0.md)
- [Phase roadmap](docs/phases/roadmap.md)
- [Data inventory](docs/research/data-inventory.md)
- [Gemini API research](docs/research/gemini-api.md)
- [Architecture decisions](docs/decisions/)

