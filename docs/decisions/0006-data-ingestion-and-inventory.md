# ADR 0006: Data ingestion and inventory boundaries

Status: accepted

## Decision

Keep format-specific CSV/XLSX readers separate from normalization, inventory metrics, delivery
contract validation, and persistence. Each source row retains raw values plus field-level
normalized values and reasons. File identity is based on SHA-256 and dataset name so repeated
ingestion is idempotent.

## Rationale

The challenge files may arrive incrementally and may disagree with the Solution Guide. A source
inspection layer lets the implementation report actual headers, worksheets, merged ranges, nulls,
duplicates, and types before business logic is applied.

## Consequences

The official delivery schema is loaded once into a JSON contract and consumed by validators and
future exporters. Unavailable runtime files are represented as unavailable inventory entries; no
headers or metrics are invented.

