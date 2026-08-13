# Phase 1 — UniLog data foundation

Status: foundation implemented; real-file execution is blocked by unavailable runtime data.

## Implemented

- CSV and XLSX readers behind a format-independent tabular read result.
- Source-file metadata including format, byte size, and SHA-256.
- Worksheet inspection including names, detected header row, headers, leading rows, and merged
  ranges.
- Typed source-row contracts preserving raw values, normalized values, and normalization reasons.
- Deterministic placeholder handling for the three official brand placeholders.
- Generated inventory metrics for nulls, placeholders, unique values, duplicate rows,
  representative values, and detected types.
- Authoritative delivery-schema extraction and validation functions.
- Content-based idempotent ingestion orchestration with a testable in-memory registry.
- PostgreSQL DDL for the required Phase 1 structures.
- CLI entry points for inventory generation and delivery validation.

## Runtime findings

The continuation specification says the two CSV files are available under `/mnt/data`. In this
Windows runtime, `/mnt/data` is not mounted, and a read-only search of common local data locations
found none of the named UniHack files. Therefore:

- no actual input row count or output header count can be claimed here;
- no official delivery headers were copied or invented;
- the generated inventory records every expected file as unavailable;
- the implementation is ready to regenerate the inventory and delivery schema when the files are
  mounted.

## Next execution

Mount or attach the real files, run `unilog-inspect-data`, review discrepancies against the
Solution Guide, persist the delivery schema JSON, and connect `IngestionService` to PostgreSQL.
Then load the official master/reference files without changing the reader or domain model.

