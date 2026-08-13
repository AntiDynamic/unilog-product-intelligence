# Database foundation

`schema.sql` defines the Phase 1 PostgreSQL tables for datasets, files, rows, raw inputs,
references, ingestion runs, and validation events.

The application assigns stable IDs and content-based idempotency keys. A PostgreSQL migration
runner and persistence adapter will be added when the real source files are mounted and the
database connection is introduced. Phase 1 does not silently substitute SQLite for PostgreSQL.

