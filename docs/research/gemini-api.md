# Gemini API research and Phase 0 decision

Research checked on 2026-08-14 against official Google AI documentation.

## Decision recorded in this repository

- SDK dependency: `google-genai`.
- Required model ID: `gemini-3.5-flash-lite`.
- Phase 0 makes no network calls.
- Simple isolated extraction should use the simplest suitable current primitive once Phase 4 is
  implemented; agentic orchestration may use the Interactions API.
- Tool calls must be executed and validated by the application. Gemini is not the source of truth.
- Structured output is a transport/schema aid, not semantic validation; application validators
  remain authoritative.
- Stateful interaction storage and caching require an explicit data-retention decision before
  product data is sent to the service.

## Official references

- [Gemini API models](https://ai.google.dev/gemini-api/docs/models)
- [Interactions API overview](https://ai.google.dev/gemini-api/docs/interactions-overview)
- [Function calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini API tools](https://ai.google.dev/gemini-api/docs/tools)
- [Python SDK repository](https://github.com/googleapis/python-genai)

