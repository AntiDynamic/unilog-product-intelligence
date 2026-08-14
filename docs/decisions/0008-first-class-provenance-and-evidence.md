# ADR 0008: First-class provenance and evidence

Status: accepted

## Decision

Sources, evidence, candidates, conflicts, validation events, and audit events are explicit typed
entities. Evidence stores concise source excerpts and locations, never hidden chain-of-thought.

## Rationale

Evidence-constrained enrichment requires more than a final value. Multiple candidates must coexist,
source authority must remain explicit, and decisions must be auditable.

## Consequences

Later Gemini or retrieval adapters must attach evidence and validation events rather than writing
directly into final delivery fields. Aggregate confidence scores are intentionally absent until a
calibrated assessment method exists.

