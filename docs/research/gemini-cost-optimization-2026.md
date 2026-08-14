# Gemini token and cost optimization — Phase 6.9

## Real-data baseline

The local UniHack input contains 1,000 rows and 76 distinct normalized manufacturer groups. The five largest groups contain 111, 108, 85, 84, and 56 rows. This makes manufacturer-level Search discovery materially cheaper than SKU-level discovery: the discovery upper bound is 76 groups before cache hits and known domains, not 1,000 products.

## Implemented reductions

- `TokenBudget` rejects oversized requests before inference.
- `estimate_context_tokens` provides a conservative local estimate; provider `count_tokens` remains the authoritative measurement when available.
- `EvidenceSelector` chooses attribute-relevant chunks instead of whole documents.
- `PromptCompressor` creates a stable short prefix and deduplicates repeated rules.
- `ManufacturerSearchCache` caches both successful and negative discovery results.
- `group_manufacturers` enables one discovery decision per normalized manufacturer.
- `cache_key` includes task/version/evidence inputs for invalidation-safe reuse.
- Cost scenarios distinguish deterministic, no-cache, implicit-cache, and Batch assumptions.

## Measured versus projected

Measured locally: 1,000 rows, 76 manufacturer groups, no Gemini calls. The previous Phase 6.6 estimate remains 800,000 input and 300,000 output tokens for 1,000 independent tasks, or `$0.99` at the configured token prices.

Projected only: a 25% implicit-cache scenario is approximately `$0.93`; a 50% Batch model-cost scenario is approximately `$0.495`. These percentages are assumptions, not measured cache hits or an invoice. Search pricing and actual query counts remain `UNKNOWN`; the 76 figure is a manufacturer-group upper bound, not a claim that 76 searches will occur.

## Quality boundary

The optimizer removes duplicate and irrelevant context, never supporting evidence. It does not truncate a source blindly, weaken source policy, or mark unsupported attributes as valid. Interactions keeps stable compact prefixes for implicit caching; explicit cached-content resources are reserved for a future measured Batch experiment because no live quota is available.

## Recommended execution

Run deterministic normalization and grouping first, resolve/reuse manufacturer sources, build compact evidence bundles, deduplicate task fingerprints, then route independent product tasks to Batch. Keep Interactions for one-product diagnostics and Search discovery. Do not spend quota on a broad live benchmark until the provider quota is restored.
