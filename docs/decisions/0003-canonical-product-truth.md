# ADR 0003: Canonical ProductTruth strategy

Status: accepted

## Decision

Maintain one canonical `ProductTruth` fact set containing identity, classification, attributes,
evidence, candidates, conflicts, validation, descriptions, and provenance. Channel-specific
content and the official delivery format are renderers/adapters over that set.

## Rationale

One fact set prevents contradictory descriptions and makes evidence and validation inspectable.
The wide official CSV must remain an external contract rather than the domain model.

## Consequences

Future renderers must not prompt independently from raw input. Any accepted fact needs traceable
evidence or an explicit deterministic source.

