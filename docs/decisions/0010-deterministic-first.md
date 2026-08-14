# ADR 0010: Deterministic processing precedes model assistance

## Decision

Use deterministic normalization, resolution, validation, diagnostics, and review signals before
any Gemini-assisted work.

## Consequences

The system can explain its preprocessing and operate safely without a model. Model output remains
candidate material and cannot conceal missing reference data.
