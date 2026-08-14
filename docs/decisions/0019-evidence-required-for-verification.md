# ADR 0019: Evidence required for verification

## Decision

An attribute cannot become publishable from model output alone. A candidate must retain a source,
evidence ID, and exact quoted evidence that belongs to an available authoritative manufacturer
source. Unsupported facts remain missing or unresolved.

## Consequences

The system may publish fewer values, but every accepted value is traceable and auditable. A future
content agent can consume canonical facts without inheriting unsupported model assumptions.
