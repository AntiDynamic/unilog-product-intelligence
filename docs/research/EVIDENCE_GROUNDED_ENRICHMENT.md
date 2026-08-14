# Evidence-grounded enrichment research note

Phase 6 treats enrichment as a constrained decision pipeline rather than an autofill prompt.

```text
ProductTruth → AttributePlan → verified evidence → candidate
             → deterministic validation → accept/review/reject → ProductTruth
```

The planner is deterministic and category-aware. The provider receives a narrow context containing
identity, planned attributes, relevant evidence chunks, and relevant rules only. Retrieved content
is untrusted data and cannot change source policy, tools, validation, or persistence access.

## Validation and review

Validation results preserve validator, severity, message, actual value, expected condition, rule,
and evidence reference. Conflicting values are kept as separate candidates and produce a structured
review payload. Missing evidence is represented as missing/unresolved, never as a guessed value.

## Evaluation harness

`EnrichmentMetrics` records operational measurements (calls, tokens, retries, cache, latency when
provided by the provider, and estimated cost). The candidate and validation DTOs are suitable for a
future field-level evaluator comparing ProductTruth against the official delivery ground truth.
This supports later A/B comparisons of model-only, model-plus-validation, and evidence-plus-
validation configurations without comparing only generated prose.

## Deferred to Phase 7

Invoice, mobile, short, long, retail, marketing descriptions, and feature prose remain outside this
phase. They may consume only accepted ProductTruth facts in the next phase.
