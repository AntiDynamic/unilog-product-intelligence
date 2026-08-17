# Phase 6.7 live experiment

## Result

The harmless Gemini smoke request passed. The first real product request reached the Gemini provider, then stopped at the Search boundary with HTTP 429 `too_many_requests`. No Google Search tool step was returned, so there is no source URL, verification, URL Context retrieval, evidence, enrichment, or validation result to claim.

The experiment correctly stopped after one product. Three- and five-product runs were not attempted because the first real product exposed a systemic quota/billing failure.

## Environment

- Model: `gemini-3.5-flash-lite`
- API mode: Interactions
- SDK version reported by the environment: `1.75.0`
- Gemini key configured: true (secret not recorded)
- Live external execution: true for the process only
- Local safety limits are local controls, not claims about Google quotas.

## Product selection

Row 2 was selected deterministically from the real 1,000-row, six-column CSV. It is a clear-identity diagnostic profile: MPN `DCB518ASTS06G`, manufacturer `Freud Inc`, with product dimensions in the description. It was not selected because it had a known successful source.

## Pipeline trace

| Stage | Result |
|---|---|
| Input inspection | PASS: 1,000 rows and expected six columns |
| Deterministic selection | PASS |
| Gemini smoke | PASS; response `OK`, request ID present, 5,406 ms |
| Gemini product request | Reached provider |
| Google Search | NOT REACHED; provider returned 429 first |
| Source verification | NOT REACHED |
| URL Context | NOT REACHED |
| Evidence extraction | NOT REACHED |
| Attribute planning/enrichment | NOT REACHED |
| Validation/ProductTruth publication | NOT REACHED |

Token and cache telemetry were unavailable from the smoke response. No Search query count can be inferred from a request that never returned a tool step.

## Failure and recommendation

The first failing category is `SEARCH_QUOTA` / provider quota. This is not evidence of malformed input, an invalid key, or a source-policy defect. Do not retry repeatedly or expand to three/five products until the active project quota or billing state is resolved. The same selected row should be rerun first.

## Phase 6.6 comparison

Phase 6.6 projected five independent tasks at approximately `$0.00495` in model-token cost. This run produced no completed product-task usage and therefore has no measured product cost. The projection remains an estimate; Search and tool costs remain unknown.

## Security

The key was supplied only through process environment. No key, authorization header, dataset copy, source cache, or raw manufacturer document is present in this report.
