# Phase 6 validation and hardening record

Date: 2026-08-14

## Data and reference audit

The supplied working input and delivery contract are usable locally, but remain private and
ignored by Git. The input has 1,000 data rows and six columns. The delivery contract has one
header row and 252 columns. Their hashes and parser/row-width checks are recorded in
[`reference-pack-audit.json`](reference-pack-audit.json).

The ten official reference files (LOVs, UOM standards, content guidelines, manufacturer/brand
lists, summary, and the 200-row comparison workbook) were not found in the project, Downloads,
or attachment roots. No LOV/UOM compliance or ground-truth accuracy metric is claimed.

## Live-readiness trace

The safe three-row dry-run parsed real rows and produced `agent_calls=0`, `candidates=0`,
`ready=0`, and `review_required=3`. This is the correct fail-closed result: the Phase 6 CLI
starts from supplied-input ProductTruth and does not silently invoke Phase 5 retrieval. The first
blocker is `MANUFACTURER_UNRESOLVED`: no verified manufacturer domain/source URL/profile and no
authoritative manufacturer evidence are attached. The next evidence gate is
`NO_VERIFIED_EVIDENCE`. The live Gemini variant was not attempted because sending local product
data to an external model requires explicit egress authorization.

See [`phase-6-live-readiness.json`](phase-6-live-readiness.json) for the machine-readable trace.

## Hardening checks

| Area | Result | Evidence |
| --- | --- | --- |
| Source policy | Pass | retrieval tests cover verified manufacturer subdomains and marketplace rejection; Phase 6 validation rejects supplied-input, low-authority, unavailable, and non-manufacturer sources |
| Evidence lineage | Pass | candidates require evidence IDs, quoted text, available authoritative/high sources, and source content hashes |
| Cache invalidation | Pass | cache keys use canonical JSON and include product, plans, evidence content hashes, prompt, model, and schema versions |
| Idempotency | Pass | duplicate candidate/evidence/conflict guards plus stable database upserts prevent repeat-run duplication |
| Inferred values | Pass | inferred/calculated candidates remain `INFERRED`, emit a warning, and can never make publication `READY` |
| Persistence | Pass | injected PostgreSQL DB-API adapter commits atomically, rolls back/closes on failure, and uses stable validation IDs |
| Private data handling | Pass | challenge files live under local/external data paths and are excluded from tracked/public paths |
| External-call safety | Pass | no provider call occurs without verified evidence; live egress was not attempted without authorization |

## Verification commands

```powershell
.venv\Scripts\ruff.exe check src tests scripts
.venv\Scripts\mypy.exe src
.venv\Scripts\pytest.exe -q
```

Focused hardening coverage includes cache-content invalidation, inferred publication gating,
repeat-run idempotency, transactional persistence commit/rollback, and existing retrieval/source
policy tests. The official 200-row ground-truth comparison remains pending until that file is
provided locally.
