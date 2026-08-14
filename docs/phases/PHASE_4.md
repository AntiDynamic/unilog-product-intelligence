# Phase 4 — Gemini Agent Orchestration

## Scope

Phase 4 introduces one bounded orchestrator and three schema-constrained agents: Product Understanding, Classification, and Attribute Extraction. Gemini output is untrusted transport data: Pydantic validates it before it is mapped into evidence-linked `ProductTruth` candidates. No candidate becomes verified because a model returned it.

## Design

The runtime uses `google-genai` and the Gemini Interactions API for isolated structured calls. Interactions are selected because the current API supports a JSON Schema response format; no remote interaction state is required for these short, independent tasks. The application, not Gemini, owns state, retries, caching, validation, and audit records.

The flow is `RECEIVED → PREPROCESSED → UNDERSTANDING → UNDERSTOOD → CLASSIFYING → CLASSIFIED → EXTRACTING → EXTRACTED → VALIDATING → CANDIDATES_ACCEPTED`, with `FAILED` as the bounded failure terminal. Prompts are file-backed and versioned under `agents/prompts/`; stable instructions precede the variable record context.

## Guardrails

The prompt contract prohibits product-text prompt injection, invented evidence, taxonomy nodes, manufacturer data, URLs, and unsupported specifications. Registry unavailability remains explicit. The in-memory deduplication key contains task, rendered input, and prompt version. Provider telemetry records request ID, token fields when exposed, latency, and retry count without fabricating absent data.

## Deferred

Manufacturer retrieval, search, crawling, enrichment, commerce descriptions, UI, persistent job/audit storage, batch queueing, and cost-rate estimation remain Phase 5+ work. The real UniHack CSV is not mounted in this workspace, so no real-row execution is claimed.
