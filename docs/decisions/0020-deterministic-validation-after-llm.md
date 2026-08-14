# ADR 0020: Deterministic validation after LLM enrichment

## Decision

Gemini proposes structured candidates. Application code performs applicability, source, evidence,
LOV, UOM, format, and conflict validation before ProductTruth is updated.

## Consequences

Validation is reproducible, inspectable, and testable without Gemini. Model confidence is retained
as metadata only and is never the publication decision.
