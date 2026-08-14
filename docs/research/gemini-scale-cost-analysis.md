# Gemini scale and cost analysis

## Measured

- Model: `gemini-3.5-flash-lite`
- Interactive smoke request: succeeded after SDK/API compatibility fix.
- Search request: provider returned HTTP 429 `too_many_requests`; no Search result was accepted.
- Provider quota values: unknown at runtime.

## Dry-run projection from the real input

The 1,000-row UniHack CSV was read locally without network calls. Using the explicit planner defaults (800 input tokens and 300 output tokens per independent task), the projection is 1,000 batchable tasks, 800,000 input tokens, 300,000 output tokens, and approximately `$0.99` at the configured token prices (`$0.30/M` input and `$2.50/M` output). A five-row plan is 4,000 input tokens, 1,500 output tokens, and approximately `$0.00495`.

These are estimates, not an invoice. Search query count and Search pricing are intentionally `UNKNOWN` until provider telemetry supplies actual query counts and the current account pricing is configured. Search is therefore modeled as a separate scarce discovery phase grouped by manufacturer, not once per SKU.

## Architecture decision

Use Interactions for one-product diagnostics and tool-aware source discovery. Use Batch/generateContent for independent bulk model tasks after deterministic filtering, manufacturer/source caching, and task deduplication. `QuotaGuard` limits local RPM, token, daily request, cost, and Search budgets; provider limits remain explicitly unknown. A 429 pauses/defer work rather than creating a retry storm.
