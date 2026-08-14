# Database foundation

`schema.sql` defines the Phase 1 PostgreSQL tables for datasets, files, rows, raw inputs,
references, ingestion runs, and validation events.

The application assigns stable IDs and content-based idempotency keys. A PostgreSQL migration
runner remains a deployment concern; Phase 6 provides an injected persistence adapter when a
database connection is supplied. Phase 1 does not silently substitute SQLite for PostgreSQL.
Phase 6 adds `src/unilog_product_intelligence/enrichment/persistence.py`, a transactional DB-API-shaped PostgreSQL adapter for plans, candidates, validation results, review payloads, and enrichment cache rows. Composition code injects a configured connection; no driver is imported or opened implicitly, and SQLite is not substituted.
