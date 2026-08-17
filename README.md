# UniLog Product Intelligence

Evidence-constrained product intelligence for industrial commerce.

This repository is the Phase 2 canonical ProductTruth implementation for the UniHack 2026 challenge. The
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
- semantic ProductTruth entities, lifecycle rules, provenance/evidence, conflicts, audit events, and delivery boundary.

The supplied UniHack input and delivery-contract CSVs are available locally and are deliberately excluded from Git. The official ten-file reference pack, including the 200-row comparison workbook, is not available; no LOV/UOM compliance or ground-truth accuracy claim is made. Phase 6 evidence-grounded enrichment, deterministic validation, bounded repair, cache invalidation, idempotency guards, and an injected PostgreSQL persistence adapter are implemented. Live model egress remains evidence-gated and requires explicit authorization.
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

## Pipeline Execution & Benchmark Modes

UNILOG supports two distinct, transparent execution modes:

### Mode A: `LIVE_DETERMINISTIC` (Default)
Fast, zero-cost deterministic baseline for measuring HTTP retrieval, taxonomy classification, and normalization rules.
```powershell
python scripts/run_pipeline.py --mode live-deterministic --limit 50 --output delivery_det_50.csv
python scripts/evaluate_delivery_50.py --output delivery_det_50.csv --traces delivery_det_50_traces.json
```
- **Provider**: `DeterministicEvaluationProvider`
- **Gemini API Cost**: $0.00 (0 API calls, 0 tokens)
- **Retrieval**: Live HTTP fetching on verified manufacturer domains
- **Purpose**: Fast regression testing of domain resolution, MPN normalization, and source discovery.

### Mode B: `LIVE_GEMINI`
Real end-to-end AI product intelligence with evidence-grounded Gemini enrichment.
```powershell
python scripts/run_pipeline.py --mode live-gemini --limit 50 --output delivery_gemini_50.csv
python scripts/evaluate_delivery_50.py --output delivery_gemini_50.csv --traces delivery_gemini_50_traces.json
```
- **Provider**: `GeminiProvider` (requires `GEMINI_API_KEY`)
- **Model**: `gemini-3.5-flash-lite` (or configured `GEMINI_MODEL`)
- **Telemetry**: Captures real model request IDs, token usage, latency, and tool calls per phase.
- **Fail-Closed**: Aborts immediately with `GeminiConfigurationError` if `GEMINI_API_KEY` is missing (no silent fallback).
- **Purpose**: Real commerce-ready AI enrichment and feature extraction.

## Scope and next step

The next safe increment is to place any supplied official reference files under the local `data/external/` directory, rerun the reference audit, and then provide an explicitly authorized manufacturer-source/evidence set for a bounded live run. PostgreSQL persistence is available through the injected Phase 6 adapter; no implicit database connection is opened. See
[the Phase 1 record](docs/phases/PHASE_1.md), [the data-foundation notes](docs/research/DATA_FOUNDATION.md),
[the phase roadmap](docs/phases/roadmap.md), and [the development guide](DEVELOPMENT.md).


## Documentation

- [Architecture](ARCHITECTURE.md)
- [Development](DEVELOPMENT.md)
- [Phase 0 record](docs/phases/phase-0.md)
- [Phase 1 record](docs/phases/PHASE_1.md)
- [Phase 2 record](docs/phases/PHASE_2.md)
- [Phase roadmap](docs/phases/roadmap.md)
- [Data inventory](docs/research/data-inventory.md)
- [Data foundation](docs/research/DATA_FOUNDATION.md)
- [Gemini API research](docs/research/gemini-api.md)
- [Architecture decisions](docs/decisions/)
- [Canonical domain model](src/unilog_product_intelligence/domain/truth.py)
## Phase 3 update

The supplied input and delivery-template CSVs are now inspected without copying product rows. Phase 3
adds deterministic registries, conservative resolution outcomes, duplicate review signals, validation,
and an observed-header delivery projection. See [the Phase 3 record](docs/phases/PHASE_3.md),
[the deterministic-intelligence notes](docs/research/DETERMINISTIC_INTELLIGENCE.md), and the generated
[aggregate diagnostic](docs/research/phase-3-diagnostic.json).

## Phase 6 local run

Keep challenge/reference files in `data/external/` (ignored by Git), or pass an explicit local path:

```powershell
.venv\Scripts\python.exe -m unilog_product_intelligence.enrichment.cli `
  --input "data/external/Unihack_ Sample Dataset - Input.csv" --limit 3
```

The run is fail-closed when no verified manufacturer evidence is attached. Read the generated
[reference-pack audit](docs/research/reference-pack-audit.json) and
[Phase 6 readiness record](docs/research/phase-6-validation.md) before enabling any authorized
live model run.
