# Architecture

## Product boundary

UniLog Product Intelligence is an evidence-constrained enrichment pipeline, not a generic
chatbot, generic RAG application, or unconstrained LLM wrapper.

```text
source records and approved references
                ↓
      UNDERSTAND → ENRICH → NORMALIZE
                ↓
             ProductTruth
                ↓
        VALIDATE → COMPOSE → DELIVER
```

`ProductTruth` is the canonical internal representation. Channel descriptions and the official
UniHack delivery format are downstream projections of this representation; they must not be
generated independently from the raw input.

## Phase 1 data foundation

The `src/` package separates:

- `domain/`: provider-independent canonical concepts and typed schemas;
- `data/`: format readers, normalization, inventory, delivery contract validation, and idempotent orchestration;
- `providers/`: the `LLMProvider` port and vendor adapters;
- `config.py`: validated runtime configuration and secret contracts;
- `api.py`: the thin FastAPI composition boundary.

CSV and XLSX readers preserve raw values. Normalization adds a separate normalized value and reason
for known placeholders, including `-- Unbranded --`, `-- No Unilog Brand --`, and
`-- No DIB Brand --`. The PostgreSQL DDL in `database/schema.sql` is the persistence foundation.

The official delivery CSV remains an external contract. Its headers are extracted once into one
machine-readable schema definition and validated for missing/unexpected headers, order changes,
duplicate headers, and invalid row widths.

## Dependency direction

```text
API/composition → application services → domain ports → adapters
                                  ↘ persistence and source adapters
```

The domain must not import FastAPI, database clients, or a Gemini client. The Gemini adapter is
the only Phase 0 module importing `google-genai`; the rest of the application depends on the
provider-neutral port.

The data layer does not import the product domain or Gemini provider. It emits typed source rows
that later application services may map into `ProductTruth`.

## Source and evidence policy

Every accepted enrichment fact must be attributable to supplied input, approved Unilog reference
data, or an allowed manufacturer source. AI-generated values remain candidates until application
validation accepts them. Marketplace and distributor pages are not authoritative manufacturer
evidence.

## External delivery contract

The supplied UniHack delivery CSV is an external adapter contract. It must preserve the supplied
headers exactly, including order and spelling. The wide delivery representation must not become
the internal domain model.
## Canonical ProductTruth boundary

`ProductTruth` is the semantic internal model between raw UniLog input and delivery. It contains
structured identity, classification, attributes, descriptions, digital assets, sources, evidence,
candidates, conflicts, validation events, audit events, lifecycle state, and explicit quality
factors. Raw ingestion snapshots remain separate and immutable.

The delivery adapter is isolated in `delivery/adapter.py`. It refuses to invent exact mappings when
the observed delivery contract is unavailable. Source authority and evidence are explicit; model
confidence is separate from system assessment, and no aggregate confidence score is claimed.

Phase 2 lifecycle transitions are constrained by `domain/lifecycle.py`:

```text
RAW → UNDERSTOOD → CLASSIFIED → ENRICHED → VALIDATED → READY → DELIVERED
```

`REVIEW_REQUIRED`, `BLOCKED`, and `CONFLICTED` are explicit intermediate states.
## Phase 3 deterministic intelligence

`deterministic/` sits ahead of future enrichment services. It contains reversible normalizers,
reference-registry interfaces, review-only fuzzy candidates, duplicate assessments, structural
validators, metrics, and aggregate diagnostics. Registries are unavailable by default until
approved reference data is loaded. The delivery adapter now preserves the observed 252-column
contract and projects only raw input fields whose names already occur in that contract.
## Phase 4 Gemini orchestration

Phase 4 adds a provider-neutral `LLMProvider` implementation backed by the required `gemini-3.5-flash-lite` model and current Gemini Interactions structured-output primitive. `ProductOrchestrator` owns the bounded state machine and invokes Product Understanding, Classification, and Attribute Extraction specialists with versioned file-backed prompts. Strict Pydantic DTOs are mapped through `ProductTruthService`; model output never writes directly to persistence or verified truth.

Deterministic application tools expose only typed manufacturer/brand/taxonomy/LOV/UOM/fraction lookups and structural attribute validation. Unloaded registries return `reference_data_unavailable`. No search, web retrieval, content generation, UI, arbitrary SQL/filesystem/HTTP, or recursive agent spawning is enabled. Provider telemetry preserves latency, request IDs, token fields when available, and retry counts; cache keys include task, prompt version, and rendered context.
## Phase 5 manufacturer intelligence

Phase 5 introduces a policy-controlled external-source boundary. `DomainResolver` and `ManufacturerDiscoveryAgent` may produce candidate domains, but `SourceVerifier` is the only authority gate. Verified manufacturer domains form an allowlist; marketplace/distributor hosts are permanently non-authoritative. `SourceFetcher` is the only HTTP boundary and enforces protocol, size, timeout, retry, rate, and content-hash constraints. `HtmlParser`/`PdfParser` produce location-preserving documents before `EvidenceExtractor` uses structured Gemini output and URL Context for a specific approved URL. Search is reserved for unresolved discovery.

Source cache, retrieval, document, chunk, and evidence-candidate tables are defined in `database/schema.sql`. Retrieved content is untrusted data and cannot override policies. Phase 5 attaches evidence-linked candidates and preserves conflicts; Phase 6 performs evidence-grounded enrichment.
## Phase 6 evidence-grounded enrichment

Phase 6 adds `enrichment/`: a deterministic category-aware `AttributePlanner`, a narrow
`EvidenceGroundedEnrichmentAgent`, and a structured `ValidationPipeline`. Provider output remains a
candidate until source/evidence, applicability, LOV, UOM, format, and conflict checks pass.
`EnrichmentService` applies accepted candidates through the ProductTruth service and emits audit,
validation, conflict, and human-review payloads. `ReferencePack` reports
`REFERENCE_AVAILABLE`/`REFERENCE_UNAVAILABLE` explicitly; missing official vocabularies are never
fabricated. Publication is a deterministic `READY`, `REVIEW_REQUIRED`, or `BLOCKED` decision.
Commerce descriptions remain deferred to Phase 7.

## Hardened Evidence Architecture (Phase 6.5)

The hardened evidence architecture enforces strict evidence invariants, guarantees deep immutability across phase boundaries, prevents AI hallucination, and provides end-to-end truth auditing.

### Core Architectural Principle

> **Gemini is a proposal and reasoning component, never an authoritative source.**
> It selects and reasons between existing evidence records — it does not create evidence or override source authority.

```text
Phase 5 (ManufacturerIntelligenceService)
       ↓  Assembles deeply immutable packet
ProductEvidencePacket (frozen=True, StructuredSpec, FeatureEvidence)
       ↓
EvidenceConstraintValidator (rejects ungrounded / hallucinated proposals)
       ↓
ConflictEngine (authority ranking: AUTHORITATIVE > HIGH > SECONDARY > UNKNOWN)
       ↓  (Equal authority: escalates via GeminiRouter strong model)
ConflictEscalationResult (pinned to valid packet evidence IDs)
       ↓
TruthAudit & FinalAttribute Provenance (audits all grounded attributes & invariants)
       ↓
Phase65ResultDeliveryAdapter (projects verified truth into official 252-column delivery)
```

### Components and Contracts

1. **Deeply Immutable `ProductEvidencePacket`** (`domain/evidence_packet.py`, `domain/models.py`)
   - `frozen=True` and `extra="forbid"`.
   - Uses domain value types (`StructuredSpec`, `FeatureEvidence`, `DiscoveredAsset`) with tuple collections (no mutable dicts or lists).
   - Single source of truth flowing from Phase 5 through Phase 6 to Delivery.

2. **`EvidenceConstraintValidator` & `EvidenceSupportValidator`** (`enrichment/evidence_validator.py`, `enrichment/evidence_support.py`)
   - Validates all `AttributeProposal` items returned by Gemini.
   - Enforces that every proposal cites non-empty `evidence_ids` that exist in `packet.evidence`.
   - `EvidenceSupportValidator` mechanically verifies that the text in cited `EvidenceReference` records supports the proposed value (numeric, UOM, range, and categorical token matching), rejecting hallucinations that cite real evidence IDs.
   - Rejects ungrounded or unsupported proposals before they can touch `ProductTruth`.

3. **Evidence-Aware `ConflictEngine` & Escalation** (`enrichment/conflicts.py`, `domain/conflict_escalation.py`)
   - Strictly higher source authority automatically wins (`AUTHORITATIVE_SOURCE_WINS`).
   - Equal top-authority disagreements (e.g. OEM HTML vs OEM PDF) are escalated to strong reasoning models via `ConflictEngine.escalate()`.
   - `ConflictEscalationResult` validates that the selected evidence ID belongs to the packet. If the model hallucinates an ID, it safely falls back to `REVIEW_REQUIRED`.

4. **`GeminiRouter` & `InferenceBudget`** (`providers/gemini_router.py`, `enrichment/inference_budget.py`)
   - Explicit retry matrix: `NON_RETRYABLE_STATUS_CODES` (400, 401, 403, 404, 422, SPEND_LIMIT) fail fast; `RETRYABLE_STATUS_CODES` (408, 429, 5xx, RESOURCE_EXHAUSTED) route to fallback.
   - `InferenceBudget` bounds LLM calls, token usage, and cost per product run.

5. **`ManufacturerRegistry` Trust Model** (`retrieval/manufacturer_registry.py`)
   - Thread-safe registry storing audited static profiles and `VerifiedRoute` instances.
   - Requires valid `evidence_id` and `{mpn}` placeholder for all learned routes.
   - Supports TTL-based expiration and automatic route pruning. Audited static profiles can never be overridden.

6. **`TruthAudit` Publication Gate & Field Provenance** (`validation/truth_audit.py`, `domain/provenance.py`, `application/phase65.py`)
   - `FinalAttribute` tracks value, unit of measure, `ProvenanceKind`, `evidence_id`, `source_url`, and `source_authority`.
   - `TruthAudit` acts as a hard delivery gate (`publication_safe`). Any ungrounded attribute assertion, evidence ID mismatch, or unresolved conflict actively transitions the product to `Phase65Status.BLOCKED` (`blocker = "TRUTH_AUDIT_VIOLATION"`).
   - Real HTML golden fixtures (`tests/golden/fixtures/`) continuously enforce extraction $\to$ packet $\to$ audit invariants across manufacturers.
