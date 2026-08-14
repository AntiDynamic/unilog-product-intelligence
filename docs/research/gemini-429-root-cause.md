# Gemini 429 root-cause hardening

No live request was made for this hardening pass.

## Findings

- The observed real-product failure was HTTP 429 before a Search tool step. Search is therefore not established as the cause.
- The provider previously had an application retry loop around `client.interactions.create`; the default is now zero application retries to avoid multiplying SDK retries.
- QuotaGuard now uses a rolling 60-second input-token window rather than lifetime input usage and enforces the configured per-product cost budget.
- A provider-scoped circuit breaker can stop new work after repeated 429s and permits a cooldown probe.
- Typed 429 metadata now distinguishes quota dimensions without guessing when structured provider fields are unavailable.
- Provider limits remain `UNKNOWN`; AI Studio/project billing is required to identify RPM, TPM, RPD, spend, or tier restrictions.

## SDK consistency

`pyproject.toml` declares `google-genai>=2.0,<3.0`. The runtime previously reported `1.75.0`, so the environment is not yet reproducibly aligned with the declaration. `uv.lock` must be regenerated in the canonical environment before the next live test; no live call should be used to resolve this discrepancy.

## Retry behavior

The fixed policy is: QuotaGuard → provider boundary → official SDK retry behavior. Application-level retries are disabled by default. Quota exhaustion is deferred, not hammered. Deterministic processing may continue while the Gemini circuit is open.
