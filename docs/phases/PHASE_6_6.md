# Phase 6.6 — quota, cost, and scale hardening

Phase 6.6 separates interactive agentic work from bulk work. `INTERACTIONS` is reserved for a single product or tool-aware diagnostic; independent product tasks route to `BATCH`; deterministic normalization and validation remain `DETERMINISTIC`.

`QuotaGuard` contains conservative local safety budgets. Provider limits are deliberately reported as `UNKNOWN` unless the runtime exposes them. `SearchBudget` treats manufacturer discovery as a scarce, manufacturer-scoped operation. `task_fingerprint` supports stable deduplication, and `estimate_batch` provides a dry-run projection without making network calls.

Use `unilog-gemini-diagnostics` to inspect configuration without exposing credentials and `unilog-cost-plan --input <csv> --limit 5` for a real-data projection. The plan is an estimate, not a bill; Search pricing is `null` unless configured from an authoritative current price.

The 429 observed in the first live Search attempt is recorded as a provider rate/quota failure. It is not treated as proof of a fixed project limit. No 1,000-row live run is permitted by this phase.
