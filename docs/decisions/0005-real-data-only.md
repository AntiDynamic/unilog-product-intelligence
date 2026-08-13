# ADR 0005: Real-data-only development policy

Status: accepted

## Decision

Never invent product records for tests, demos, UI, or backend responses. Product values must come
from supplied input, approved Unilog references, permitted manufacturer sources, deterministic
transformations, or explicitly marked AI candidates.

## Rationale

Synthetic product values would make quality claims and challenge evaluation misleading.

## Consequences

Unit tests use empty typed models or metadata-only fixtures. Integration tests will require actual
approved files and will record their provenance.

