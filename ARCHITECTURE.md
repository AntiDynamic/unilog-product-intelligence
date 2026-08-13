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

## Phase 0 boundaries

The initial package uses a `src/` layout and separates:

- `domain/`: provider-independent canonical concepts and typed schemas;
- `providers/`: the `LLMProvider` port and vendor adapters;
- `config.py`: validated runtime configuration and secret contracts;
- `api.py`: the thin FastAPI composition boundary.

No database, ingestion, enrichment, model call, web fetch, or frontend is implemented in Phase 0.

## Dependency direction

```text
API/composition → application services → domain ports → adapters
                                  ↘ persistence and source adapters (future)
```

The domain must not import FastAPI, database clients, or a Gemini client. The Gemini adapter is
the only Phase 0 module importing `google-genai`; the rest of the application depends on the
provider-neutral port.

## Source and evidence policy

Every accepted enrichment fact must be attributable to supplied input, approved Unilog reference
data, or an allowed manufacturer source. AI-generated values remain candidates until application
validation accepts them. Marketplace and distributor pages are not authoritative manufacturer
evidence.

## External delivery contract

The supplied UniHack delivery CSV is an external adapter contract. It must preserve the supplied
headers exactly, including order and spelling. The 252-column delivery representation must not
become the internal domain model.

