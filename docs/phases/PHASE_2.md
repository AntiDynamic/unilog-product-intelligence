# Phase 2 — Canonical ProductTruth

Status: implemented; exact delivery mappings remain blocked by unavailable official files.

## Implemented

- Typed `ProductTruth` semantic model separate from the delivery format.
- Identity fields with raw/canonical values, status, source IDs, evidence IDs, and assessment metadata.
- Structured attributes with applicability, UOM, lifecycle status, candidates, evidence, and validation state.
- Source and evidence entities with explicit authority and evidence types.
- Candidate coexistence and first-class conflicts with explicit resolution states.
- Separate model confidence from system assessment factors; no fake aggregate confidence score.
- Frozen raw input snapshots retaining raw values and normalization reasons.
- Product lifecycle transition table with invalid-transition errors.
- Append-oriented validation and audit event models.
- Deterministic `ProductTruthService` interfaces for creation, identity/classification updates,
  candidates, evidence, validation, conflicts, and conflict resolution.
- Delivery adapter boundary that refuses to invent mappings when the official contract is unavailable.
- PostgreSQL tables for products, attributes, candidates, canonical sources, evidence, conflicts,
  and audit events.

## Runtime findings

The Phase 1 machine-readable inventory still records all 12 expected UniHack files as unavailable
in this Windows runtime. No delivery headers, LOV values, taxonomy values, manufacturer counts, or
other official reference data were invented.

## Lifecycle

```text
RAW → UNDERSTOOD → CLASSIFIED → ENRICHED → VALIDATED → READY → DELIVERED
```

`REVIEW_REQUIRED`, `BLOCKED`, and `CONFLICTED` are explicit intermediate states. Transitions are
validated by `domain/lifecycle.py`; arbitrary state changes are rejected.

## Deferred work

- Real delivery field mappings after the official CSV is available.
- PostgreSQL persistence adapter and migrations.
- Manufacturer retrieval, Gemini extraction, normalization rules, LOV validation, and enrichment.
- Description generation and delivery export.

