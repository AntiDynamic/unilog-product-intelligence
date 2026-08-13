-- PostgreSQL foundation for Phase 1.
-- IDs are application-assigned content/stable identifiers so retries are idempotent.

CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('input', 'delivery_contract', 'reference')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dataset_files (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets(id),
    path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('csv', 'xlsx', 'docx', 'pdf')),
    sha256 TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (dataset_id, sha256)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id TEXT PRIMARY KEY,
    dataset_file_id TEXT NOT NULL REFERENCES dataset_files(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed', 'skipped')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS dataset_rows (
    id TEXT PRIMARY KEY,
    dataset_file_id TEXT NOT NULL REFERENCES dataset_files(id),
    row_number INTEGER NOT NULL,
    raw_values JSONB NOT NULL,
    normalized_values JSONB NOT NULL,
    row_sha256 TEXT NOT NULL,
    UNIQUE (dataset_file_id, row_number)
);

CREATE TABLE IF NOT EXISTS raw_product_inputs (
    id TEXT PRIMARY KEY,
    dataset_row_id TEXT NOT NULL UNIQUE REFERENCES dataset_rows(id),
    raw_payload JSONB NOT NULL,
    normalized_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reference_sources (
    id TEXT PRIMARY KEY,
    dataset_file_id TEXT REFERENCES dataset_files(id),
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('unilog_master', 'manufacturer', 'other')),
    source_url TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reference_records (
    id TEXT PRIMARY KEY,
    reference_source_id TEXT NOT NULL REFERENCES reference_sources(id),
    record_key TEXT,
    raw_payload JSONB NOT NULL,
    normalized_payload JSONB NOT NULL,
    UNIQUE (reference_source_id, record_key)
);

CREATE TABLE IF NOT EXISTS validation_events (
    id TEXT PRIMARY KEY,
    ingestion_run_id TEXT REFERENCES ingestion_runs(id),
    dataset_row_id TEXT REFERENCES dataset_rows(id),
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dataset_rows_file ON dataset_rows(dataset_file_id);
CREATE INDEX IF NOT EXISTS idx_reference_records_source ON reference_records(reference_source_id);
CREATE INDEX IF NOT EXISTS idx_validation_events_run ON validation_events(ingestion_run_id);

