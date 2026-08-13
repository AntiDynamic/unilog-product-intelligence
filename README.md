# UniLog Product Intelligence

Evidence-constrained product intelligence for industrial commerce.

This repository is the Phase 1 data-foundation implementation for the UniHack 2026 challenge. The
planned system transforms limited, messy product information into reliable, standardized,
commerce-ready intelligence through:

```text
UNDERSTAND → ENRICH → NORMALIZE → VALIDATE → COMPOSE → DELIVER
```

AI may propose facts. Evidence, controlled vocabularies, business rules, and validators decide
whether a fact becomes final product data.

## Current status

Phase 0 is complete and the Phase 1 foundation is implemented:

- typed Python package with a FastAPI application factory and operational health endpoint;
- provider-neutral `LLMProvider` port with configuration-only Gemini and future local adapters;
- initial `ProductTruth` domain boundary with provenance and evidence fields;
- secure environment contract for `GEMINI_API_KEY`;
- pytest, Ruff, mypy, and GitHub Actions configuration;
- architecture, development, ADR, research, and phase-roadmap documentation;
- CSV/XLSX readers with raw-value preservation and field-level normalization provenance;
- generated data inventory and official-delivery header validation;
- PostgreSQL foundation DDL for datasets, files, rows, references, ingestion, and validation.

The real UniHack files listed by the challenge were not mounted in this Windows runtime, so the
checked-in inventory records them as unavailable. No product records, fabricated examples,
Gemini calls, enrichment pipeline, frontend, or mock product responses have been added.

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
uv run pytest --basetemp .pytest-tmp
uv run unilog-inspect-data --data-root /mnt/data
```

When the actual delivery CSV is available, extract its contract once and validate future exports:

```powershell
python -c "from unilog_product_intelligence.data.delivery import save_delivery_schema; save_delivery_schema('Unihack_ Expected Output - Delivery Format.csv', 'docs/research/delivery-schema.json')"
uv run unilog-validate-delivery path/to/delivery.csv docs/research/delivery-schema.json
```

## Scope and next step

The next implementation increment is to mount the real files and run the generated inspection,
then load official master/reference data and persist ingestion runs in PostgreSQL. See
[the Phase 1 record](docs/phases/PHASE_1.md), [the data-foundation notes](docs/research/DATA_FOUNDATION.md),
[the phase roadmap](docs/phases/roadmap.md), and [the development guide](DEVELOPMENT.md).

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Development](DEVELOPMENT.md)
- [Phase 0 record](docs/phases/phase-0.md)
- [Phase 1 record](docs/phases/PHASE_1.md)
- [Phase roadmap](docs/phases/roadmap.md)
- [Data inventory](docs/research/data-inventory.md)
- [Data foundation](docs/research/DATA_FOUNDATION.md)
- [Gemini API research](docs/research/gemini-api.md)
- [Architecture decisions](docs/decisions/)