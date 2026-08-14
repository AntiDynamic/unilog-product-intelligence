# ADR 0022: Evidence-aware enrichment cache invalidation

## Decision

An enrichment result is reusable only when product identity, relevant plans, evidence references,
prompt version, model version, and schema/rules version are unchanged.

## Consequences

Source changes and rule changes force revalidation. Stable repeated runs are idempotent and avoid
duplicate provider cost without serving stale decisions.
