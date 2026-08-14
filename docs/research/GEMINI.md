# Gemini integration research

Checked 2026-08-14 against Google AI documentation. The implementation uses the required configured model ID `gemini-3.5-flash-lite` through the current `google-genai` SDK and `client.interactions.create`. Interactions with `response_format` JSON Schema are used for short structured extraction tasks; the implementation does not use remote state or built-in retrieval tools.

Google documents JSON Schema structured output and Pydantic-compatible schemas for predictable extraction. Function calling is deliberately deferred in the SDK adapter: application registry operations remain narrow deterministic capabilities and are not exposed as arbitrary database, filesystem, HTTP, or SQL tools.

Official references: [structured output](https://ai.google.dev/gemini-api/docs/structured-output), [Interactions](https://ai.google.dev/gemini-api/docs/interactions-overview), and [function calling](https://ai.google.dev/gemini-api/docs/function-calling).
