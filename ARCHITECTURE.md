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
