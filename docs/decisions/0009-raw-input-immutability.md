# ADR 0009: Raw input immutability

Status: accepted

## Decision

`ProductTruth.raw_inputs` is a tuple of frozen `RawInputField` snapshots. Canonical identity and
attribute values may evolve, but the original raw value, normalization result, reason, and source
ID remain available for audit.

## Rationale

Placeholder handling and future enrichment must never make it impossible to answer what the
source actually contained.

## Consequences

Transformations append audit events and update canonical fields without mutating raw snapshots.
Persistence must keep raw ingestion tables separate from canonical product tables.

