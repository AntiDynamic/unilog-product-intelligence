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