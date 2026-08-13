# Phase 0 — Project bootstrap and engineering foundation

Status: complete for the local workspace.

## Implemented

- Initialized the existing empty Git repository.
- Added a Python package using `pyproject.toml` and a `src/` layout.
- Added FastAPI application factory and operational `/health` endpoint.
- Added Pydantic settings with `GEMINI_API_KEY` and the explicit model ID
  `gemini-3.5-flash-lite`.
- Added the provider-neutral `LLMProvider`, `GeminiProvider`, and future `LocalProvider` slot.
- Added typed `ProductTruth`, identity, attribute, evidence, and provenance boundaries.
- Added tests for configuration, domain defaults, provider call guardrails, and health.
- Added Ruff, mypy, pytest, and GitHub Actions CI configuration.
- Added architecture, development, research, roadmap, and ADR documentation.
- Inspected the Windows workspace and recorded that `/mnt/data` is not mounted here.

## Explicitly not implemented

- No real Gemini request.
- No product ingestion or fabricated product data.
- No PostgreSQL schema or migrations.
- No manufacturer web fetching or source discovery.
- No enrichment, normalization, validation, content generation, delivery export, or frontend.

## Exit criteria

The repository has a reproducible package boundary, typed extension points, secure secret
handling, documented decisions, and automated quality checks. Phase 1 can now begin without
changing the core provider or canonical-model boundaries.

