# Phase 5 — Manufacturer Intelligence and Evidence Retrieval

Phase 5 turns ProductTruth candidates into a controlled manufacturer-source workflow:

`identity → domain candidate → deterministic verification → approved URL fetch → deterministic parse → structured evidence → ProductTruth evidence/candidates`.

## Source policy

Only an allowlisted manufacturer domain can become `verified_manufacturer_source`. Amazon, eBay, marketplaces, distributors, and other blocked domains are always non-authoritative. Search results and unknown domains remain candidates. The model never decides authority.

## Implemented boundaries

- `DomainResolver` checks verified domain cache/registry before discovery and generates deterministic query concepts only when needed.
- `ManufacturerDiscoveryAgent` can use Google Search as a candidate-discovery tool; it cannot verify or persist authority.
- `SourcePolicy`/`SourceVerifier` enforce manufacturer ownership, subdomain allowlists, and blocked-host policy.
- `SourceFetcher` enforces HTTPS/HTTP only, public-host checks, byte limits, timeouts, redirect behavior delegated to the bounded client, retry limits, per-domain spacing, content hashing, and cache status.
- `SourceCache` deduplicates fresh retrievals by canonical URL; PostgreSQL tables provide the persistence boundary for production storage.
- `HtmlParser` extracts deterministic text/title/location; `PdfParser` is an optional adapter and fails explicitly when its parser dependency is unavailable.
- `EvidenceExtractor` uses strict Pydantic output and URL Context when the Gemini adapter supports it. Retrieved content is delimited as data and cannot override policy.
- `ManufacturerIntelligenceService` preserves source metadata, evidence location, inferred-vs-direct status, and conflicting candidates. It does not perform Phase 6 enrichment.

## CLI

`unilog-phase5 --input <real-file> --limit 3 --row-id <n> --manufacturer <name> --manufacturer-domain <domain> --source-url <url> [--refresh] [--dry-run]`.

No real UniHack file is mounted in this runtime, so no live product retrieval is claimed. The CLI reports unavailable input or missing verified source inputs explicitly.

## Deferred

Persistent repository implementation, broad batch grouping, Docling installation/production PDF parsing, live Search/URL Context runs, conflict resolution, automatic attribute enrichment, commerce content, and UI belong to later work. Phase 6 consumes verified evidence to propose enriched ProductTruth candidates.
