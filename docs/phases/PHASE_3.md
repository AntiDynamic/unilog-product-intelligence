# Phase 3 — Deterministic Intelligence

## Outcome

Phase 3 adds a deterministic, evidence-safe layer between raw input and future enrichment. It
does not call Gemini and it does not ship any invented reference data.

The supplied files were inspected directly:

- input: 1,000 records with six observed source columns;
- delivery template: 252 exact headers and two example rows.

The extracted contract is stored in `docs/research/delivery-schema.json`. The aggregate input
report is stored in `docs/research/phase-3-diagnostic.json`; it contains counts and a source hash,
not copied product rows.

## Implemented capabilities

- reversible text and MPN normalization while retaining raw values;
- reference-registry interfaces for manufacturer, brand, taxonomy, LOV, UOM, fractions, and rules;
- explicit `reference_data_unavailable`, unresolved, ambiguous, and resolved outcomes;
- manufacturer-scoped brand resolution;
- exact normalized duplicate signals that never merge products;
- calculated fraction conversion marked separately from official lookup values;
- structural product and attribute validation and operation metrics;
- delivery projection that retains all 252 observed headers and maps only identically named raw
  source fields.

## Guardrails

No official manufacturer, brand, taxonomy, LOV, UOM, fraction, or rule pack was supplied. All
corresponding registries remain unavailable by default. Fuzzy similarity creates review candidates
only and cannot auto-resolve identity. Empty delivery fields are intentionally left empty until an
authoritative mapping and supported source evidence exist.

## Real-input findings

The generated diagnostic records 755 DIB-brand placeholders, 799 E1-brand placeholders, 1,000
Unilog-brand placeholders, two MPN normalization opportunities, and one exact normalized MPN
duplicate group involving two rows. These are diagnostics, not enrichment or merge decisions.

## Verification

`uv run ruff check .` and `uv run pytest --basetemp .pytest-tmp` pass (28 tests). The deterministic
package passes strict mypy. The repository-wide mypy run under the workspace's Python 3.13 reports
16 pre-existing typing errors in older tests; no Phase 3 module is among them.
