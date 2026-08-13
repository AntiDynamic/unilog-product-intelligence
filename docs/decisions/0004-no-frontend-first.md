# ADR 0004: Backend intelligence before frontend

Status: accepted

## Decision

Build and validate ingestion, canonical truth, enrichment, validation, and delivery before UX.

## Rationale

The challenge is won by reliable product intelligence. A frontend before real backend outputs
would encourage fabricated demo values and obscure data-quality failures.

## Consequences

Phase 0 contains only an operational API foundation. Phase 12 may build UX over live processed
data after backend evaluation exists.

