# ADR 0014: Treat LLM output as untrusted input

Status: accepted

Validate Gemini JSON with strict Pydantic DTOs, then map it through domain services and evidence constraints. Model output is candidate material only; it cannot become verified truth without deterministic validation and source evidence.
