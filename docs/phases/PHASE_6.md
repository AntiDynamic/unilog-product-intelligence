# Phase 6 — Evidence-Grounded Product Enrichment

Phase 6 converts canonical `ProductTruth` plus verified manufacturer evidence into constrained
attribute candidates. It intentionally stops before commerce-description generation (Phase 7).

## Pipeline

1. `AttributePlanner` selects category-specific required/optional attributes. Existing publishable
   values are not re-enriched.
2. `EvidenceGroundedEnrichmentAgent` receives only the selected plans and verified evidence
   references. Model output is a candidate, never a final value.
3. `ValidationPipeline` runs schema, applicability, evidence/source-policy, LOV, UOM, format, and
   conflict checks. Every check emits a typed `ValidationResult`.
4. `EnrichmentService` applies accepted candidates through the existing ProductTruth service,
   preserving evidence, validation events, audit events, and conflicts.
5. Publication is `READY`, `REVIEW_REQUIRED`, or `BLOCKED`; it is not a score.

## Reference-data honesty

`ReferencePack.discover()` checks the official filenames at configured roots. The result explicitly
states `REFERENCE_AVAILABLE` or `REFERENCE_UNAVAILABLE`. When unavailable, the engine does not
claim LOV/UOM compliance and emits a warning validation result instead.

## Evidence and status

Each candidate carries evidence IDs, quoted text, source metadata, raw and normalized values, UOM,
model metadata, and a stable context cache key. Final attribute statuses are explicit:
`VERIFIED`, `NORMALIZED`, `ENRICHED`, `INFERRED`, `CONFLICTED`, `MISSING`, `REJECTED`, or
`REVIEW_REQUIRED`.

Manufacturer authority is inherited from Phase 5. Supplied input, marketplace, distributor, and
unverified web sources cannot support an authoritative enrichment.

## Cost and idempotency

Planning precedes model calls, only relevant evidence is sent, and enrichment results are cached by
product, plan, evidence, prompt version, model, and schema version. No provider call is made when
there is no applicable plan or verified evidence. The CLI defaults to three rows and does not run a
large concurrent batch.

## Diagnostics

Run a controlled real-data diagnostic:

```text
unilog-phase6 --input "Unihack_ Sample Dataset - Input.csv" --limit 3 --output phase6.json
```

The JSON contains reference availability, plans, candidates, validation results, review payloads,
publication states, agent/token/cache metrics, and errors. No final descriptions are generated.

## Repair and review

Validation failures may enter a bounded repair call using the supplied evidence and rules. max_repair_attempts prevents recursion; unsuccessful repair remains REVIEW_REQUIRED. Conflicts remain separate candidates until an explicit domain decision.

## Validation and hardening

Challenge CSVs and reference files are local runtime inputs only. Place them under `data/external/`
(or pass an explicit path); the directory and known challenge filenames are ignored by Git. The
machine-readable inventory is [`docs/research/reference-pack-audit.json`](../research/reference-pack-audit.json).

The official reference pack was not found, so plans retain `REFERENCE_UNAVAILABLE` and validators
make no LOV/UOM compliance claim. A three-row safe dry-run produced zero agent calls and zero
candidates because Phase 6 starts from supplied-input ProductTruth and requires a verified
manufacturer domain/source URL plus authoritative/high evidence. The first live blocker is
`MANUFACTURER_UNRESOLVED`, followed by `NO_VERIFIED_EVIDENCE`; no external live call is attempted
without explicit egress authorization. See the [readiness record](../research/phase-6-validation.md).

`PostgresEnrichmentRepository` is an injected DB-API adapter. It transactionally upserts plans,
candidates, validation results, reviews, and cache rows; stable content IDs and duplicate guards
make retries idempotent. It does not import a driver or open a connection implicitly.
