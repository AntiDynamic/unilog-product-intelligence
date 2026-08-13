# ADR 0001: Gemini model selection

Status: accepted

## Decision

Use the explicit stable model ID `gemini-3.5-flash-lite` as the project default. Do not silently
substitute `gemini-2.5-flash-lite`, `gemini-3.1-flash-lite`, or preview Lite models.

## Rationale

The challenge requires high-volume, cost-sensitive structured product work. Pinning the model ID
makes behavior and cost reviewable. A future change requires a new ADR and validation evidence.

## Consequences

The model may eventually need a controlled migration if Google changes availability or economics.
The model ID is centralized in configuration and covered by a test.

