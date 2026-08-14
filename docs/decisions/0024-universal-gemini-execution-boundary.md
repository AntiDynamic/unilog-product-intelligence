# ADR 0024: universal Gemini execution boundary

All Gemini SDK calls must remain behind the provider module. Application callers use `GeminiExecutionService`, which is the single place that checks local quota and the provider circuit breaker before invoking `GeminiProvider`. Search and URL Context are tool modes of the same provider interaction, not separate unrestricted clients. Deterministic HTTP retrieval remains outside Gemini by design.
