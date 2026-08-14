# ADR 0007: Canonical ProductTruth versus UniHack delivery schema

Status: accepted

## Decision

`ProductTruth` is the internal semantic, source-aware, provenance-aware, validation-aware product
model. `UniHackDeliveryRecord` is an external, fixed, column-oriented adapter result. The domain
does not contain official delivery column names or the delivery schema's unobserved semantics.

## Rationale

The official delivery CSV was unavailable in the Phase 1/2 runtime. Inventing its headers or
field mappings would create an unreviewable contract and couple business logic to presentation.

## Consequences

The adapter raises an explicit pending error until the actual contract is loaded. Once available,
mapping code can be added at one boundary and validated against exact header order.

