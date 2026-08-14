# Gemini execution call graph

The approved SDK boundary is `providers/gemini.py`. Phase 4, Phase 5, and Phase 6 CLI construction now wraps the provider with `GeminiExecutionService`, which checks `QuotaGuard`, consults `QuotaCircuitBreaker`, invokes the provider, and records usage. Agents consume the abstract `LLMProvider` interface and do not import the Google SDK.

The architecture test scans all production Python files and fails if `google.genai` appears outside the provider boundary. Deterministic Phase 5 HTTP retrieval is intentionally not a Gemini SDK path.

The current repository has no Batch SDK submission implementation to audit. A future BatchProvider must use the same execution/budget boundary before submission.
