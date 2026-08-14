# Phase 6.11 — Gemini execution boundary and SDK reproducibility

This phase establishes a single application execution boundary for current interactive Gemini calls: task/agent → `GeminiExecutionService` → `QuotaGuard` → `QuotaCircuitBreaker` → `GeminiProvider` → Google SDK. The provider remains the only production module importing `google.genai`.

Application-level retry remains disabled by default after Phase 6.10. The SDK is the sole retry owner. The environment still requires lockfile reconciliation: the declared dependency is `google-genai>=2.0,<3.0`, while historical lock/runtime evidence reported `1.75.0`.
