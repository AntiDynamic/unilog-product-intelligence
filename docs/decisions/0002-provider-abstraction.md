# ADR 0002: Provider abstraction

Status: accepted

## Decision

Application code depends on the provider-neutral `LLMProvider` port. `GeminiProvider` is an
adapter, and `LocalProvider` is an explicit future slot. The SDK must not leak into domain models.

## Rationale

This keeps vendor calls, retries, telemetry, structured response handling, and secrets at the
integration boundary while preserving a path for later provider evaluation.

## Consequences

Phase 0 has no real generation method. Phase 4 must add bounded retries, observability, schema
validation, and cost metadata before enabling calls.

