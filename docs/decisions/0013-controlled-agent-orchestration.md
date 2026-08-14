# ADR 0013: Controlled agent orchestration

Status: accepted

Use one application-controlled orchestrator with three bounded, ordered specialists. Each has versioned prompts, strict input/output DTOs, explicit job state, telemetry, and deterministic mapping into candidates. Agents cannot spawn agents, access SQL/filesystem/arbitrary HTTP, or directly mutate ProductTruth.
