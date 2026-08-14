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


-- Phase 2 canonical ProductTruth structures. Raw ingestion remains in the tables above.
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    lifecycle_state TEXT NOT NULL,
    identity_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    classification_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    descriptions_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    digital_assets_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    quality_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_attributes (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    attribute_id TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    raw_value JSONB,
    normalized_value TEXT,
    uom TEXT,
    status TEXT NOT NULL,
    applicability TEXT NOT NULL,
    validation_state TEXT NOT NULL,
    source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (product_id, attribute_id)
);

CREATE TABLE IF NOT EXISTS attribute_candidates (
    id TEXT PRIMARY KEY,
    attribute_record_id TEXT NOT NULL REFERENCES product_attributes(id),
    raw_value JSONB,
    normalized_value TEXT,
    uom TEXT,
    status TEXT NOT NULL,
    assessment_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS canonical_sources (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    authority TEXT NOT NULL,
    uri TEXT,
    manufacturer_id TEXT,
    retrieved_at TIMESTAMPTZ,
    content_hash TEXT,
    status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS product_evidence (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES canonical_sources(id),
    product_id TEXT REFERENCES products(id),
    attribute_id TEXT,
    quoted_text TEXT,
    document_page INTEGER,
    location JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_type TEXT NOT NULL,
    extracted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS product_conflicts (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    attribute_id TEXT,
    candidate_ids JSONB NOT NULL,
    source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflict_type TEXT NOT NULL,
    state TEXT NOT NULL,
    recommended_candidate_id TEXT,
    resolution_reason TEXT,
    resolved_by TEXT,
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS product_audit_events (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_product_attributes_product ON product_attributes(product_id);
CREATE INDEX IF NOT EXISTS idx_attribute_candidates_attribute ON attribute_candidates(attribute_record_id);
CREATE INDEX IF NOT EXISTS idx_product_evidence_product ON product_evidence(product_id);
CREATE INDEX IF NOT EXISTS idx_product_conflicts_product ON product_conflicts(product_id);
CREATE INDEX IF NOT EXISTS idx_product_audit_events_product ON product_audit_events(product_id);
-- Phase 5 manufacturer source registry, retrieval cache, parsed documents, and evidence lineage.
CREATE TABLE IF NOT EXISTS manufacturer_domains (
    id TEXT PRIMARY KEY,
    manufacturer_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('verified_manufacturer_source', 'candidate_manufacturer_source', 'non_authoritative', 'rejected', 'unavailable')),
    source TEXT NOT NULL,
    reason TEXT NOT NULL,
    score NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (manufacturer_id, domain)
);

CREATE TABLE IF NOT EXISTS source_candidates (
    id TEXT PRIMARY KEY,
    product_id TEXT REFERENCES products(id),
    manufacturer_id TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    original_url TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    decision TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_retrievals (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES canonical_sources(id),
    canonical_url TEXT NOT NULL,
    content_hash TEXT,
    retrieval_status TEXT NOT NULL,
    cache_status TEXT NOT NULL,
    content_type TEXT,
    http_status INTEGER,
    etag TEXT,
    last_modified TEXT,
    bytes_read BIGINT,
    fetched_at TIMESTAMPTZ,
    parser_version TEXT,
    raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES canonical_sources(id),
    page_count INTEGER,
    content_hash TEXT NOT NULL,
    parser TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    parsed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_id, content_hash)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    page INTEGER,
    section TEXT,
    text TEXT NOT NULL,
    location JSONB NOT NULL DEFAULT '{}'::jsonb,
    table_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    image_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS evidence_candidates (
    id TEXT PRIMARY KEY,
    product_id TEXT REFERENCES products(id),
    source_id TEXT NOT NULL REFERENCES canonical_sources(id),
    attribute TEXT NOT NULL,
    raw_value TEXT,
    normalized_candidate TEXT,
    unit TEXT,
    source_text TEXT NOT NULL,
    page INTEGER,
    location JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_type TEXT NOT NULL,
    status TEXT NOT NULL,
    model_confidence NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_manufacturer_domains_manufacturer ON manufacturer_domains(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_source_candidates_product ON source_candidates(product_id);
CREATE INDEX IF NOT EXISTS idx_source_retrievals_url ON source_retrievals(canonical_url);
CREATE INDEX IF NOT EXISTS idx_document_chunks_document ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_evidence_candidates_product ON evidence_candidates(product_id);

-- Phase 6 evidence-grounded enrichment plans, candidates, validation, review, and cache.
CREATE TABLE IF NOT EXISTS attribute_plans (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    attribute_id TEXT NOT NULL,
    attribute_name TEXT NOT NULL,
    applicability TEXT NOT NULL,
    current_status TEXT NOT NULL,
    current_value JSONB,
    evidence_available BOOLEAN NOT NULL DEFAULT FALSE,
    enrichment_decision TEXT NOT NULL,
    validation_requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_values JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_uom JSONB NOT NULL DEFAULT '[]'::jsonb,
    reference_availability TEXT NOT NULL,
    priority INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (product_id, attribute_id)
);

CREATE TABLE IF NOT EXISTS enrichment_candidates (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    attribute_id TEXT NOT NULL,
    value JSONB,
    raw_value JSONB,
    normalized_value TEXT,
    uom TEXT,
    source_id TEXT REFERENCES canonical_sources(id),
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_text TEXT,
    status TEXT NOT NULL,
    validation_state TEXT NOT NULL,
    candidate_reason TEXT NOT NULL,
    model_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    cache_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (product_id, attribute_id, cache_key)
);

CREATE TABLE IF NOT EXISTS enrichment_validation_results (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    candidate_id TEXT REFERENCES enrichment_candidates(id),
    attribute_id TEXT,
    validator TEXT NOT NULL,
    passed BOOLEAN NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence_reference TEXT,
    rule_reference TEXT,
    actual_value JSONB,
    expected_condition TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS enrichment_reviews (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    attribute_id TEXT NOT NULL,
    current_value JSONB,
    candidate_values JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    validation_failures JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommended_action TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS enrichment_cache (
    cache_key TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    source_content_hashes JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_attribute_plans_product ON attribute_plans(product_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_candidates_product ON enrichment_candidates(product_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_validation_product ON enrichment_validation_results(product_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_reviews_product ON enrichment_reviews(product_id);
