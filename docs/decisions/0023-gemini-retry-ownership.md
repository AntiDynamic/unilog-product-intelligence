# ADR 0023: single retry owner for Gemini provider errors

## Decision

The application provider does not add a second retry loop by default (`max_retries=0`). The official Google SDK remains the retry owner for transient transport errors. QuotaGuard and the circuit breaker decide whether a logical task may start; quota exhaustion is deferred rather than repeatedly retried.

## Rationale

Nested application and SDK retries can multiply one logical request into many provider attempts during a 429 storm. A 429 with structured `rate_limit_exceeded` semantics is different from `quota_exceeded`; without reliable metadata the dimension remains `UNKNOWN` and the safe action is defer/circuit-break.

## Limits

The SDK version and active Google project quota must still be verified in the execution environment. This ADR does not claim which provider quota dimension caused the observed 429.
