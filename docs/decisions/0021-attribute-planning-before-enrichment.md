# ADR 0021: Attribute planning before enrichment

## Decision

Category schema and available LOV data determine applicable attributes before any provider call.
Gemini is used only for ambiguity within a deterministic plan.

## Consequences

Calls are smaller and cheaper, category-specific requirements are explicit, and irrelevant fields
are not filled from world knowledge.
