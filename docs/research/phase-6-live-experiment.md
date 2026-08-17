# Phase 6.5 live end-to-end validation

## 1. Objective

Measure the real pipeline without simplifying or fabricating unavailable evidence.
The experiment uses five deterministic real-row profiles and does not optimize for a successful-looking demo.

## 2. Environment and authorization

Input: `Unihack_ Sample Dataset - Input.csv` (1000 data rows, 6 columns).
Delivery contract: `Unihack_ Expected Output - Delivery Format.csv` (252 columns, 2 data rows).
Model configured: `gemini-3.5-flash-lite`; key configured: `True`.
Live Gemini/Search/URL Context calls were not attempted because external egress for local product data was not authorized.

## 3. Product-selection methodology

Selection is deterministic, non-random, and uses stable row-index tie-breaks. It covers clear identity, dimensions/UOM, embedded brand, cryptic abbreviation, and an ambiguous duplicate MPN.

| Product | Row | Profile | Manufacturer | MPN | Description |
|---|---:|---|---|---|---|
| `phase65-row-2` | 2 | clear_identity | Freud Inc (2435) | DCB518ASTS06G | DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc |
| `phase65-row-11` | 11 | dimensions_and_uom | Mirka Abrasives Inc (MIRUS) | 9A-570-240 | 9A-570-240 Abranet 2.75x30 |
| `phase65-row-162` | 162 | embedded_brand | U S Lumber (3073) | 543140016 | 1nx6-16' Biscayne Sq Edge - Trex Transcend Lineage Decking |
| `phase65-row-72` | 72 | cryptic_abbreviation | V & V Appliance Parts Inc (VVAPP) | D519127 | D519127 Heater Kit |
| `phase65-row-785` | 785 | ambiguous_duplicate_mpn | Malco Prod (2370) | AVM6EV | AVM7 EV Mini Snip Green |

## 4. Pipeline and observed result

The deterministic reader and placeholder normalization ran. The live chain stopped before Phase 4 because authorization was absent; therefore classification, manufacturer discovery, retrieval, evidence extraction, Phase 6 enrichment, and publication were not claimed as executed.

Aggregate: 5 selected, 5 review-required, 0 READY, 0 BLOCKED, 0 Gemini calls, 0 Search calls, 0 URL Context calls.

## 5. Phase 5 → Phase 6 integration finding

The current Phase 6 CLI constructs ProductTruth directly and calls EnrichmentService. It does not invoke Phase 5 when evidence is absent. This is a real missing composition boundary, not a data failure. The minimum correction is one composition-owned seam that reuses the existing Phase 4 orchestrator, ManufacturerIntelligenceService, and EnrichmentService in order.

## 6. Solution-guide comparison

The attached task specification is available; no separate Solution Guide PDF was found locally. The following are implementation observations:

| Requirement | Current observation | Result |
|---|---|---|
| Six raw input fields and placeholder handling | Reader preserves raw values and normalizes known placeholders | PASS |
| De-duplication | Deterministic duplicate signals exist; no merge is performed | PARTIAL |
| Taxonomy/classification and attribute extraction | Phase 4 agents exist but were not live-executed | NOT_VALIDATED |
| Manufacturer-source enrichment | Phase 5 policy/retrieval exists; Phase 5→6 invocation is absent | PARTIAL |
| Evidence/provenance and validation | Phase 6 contracts and gates exist; no live evidence in this run | PARTIAL |
| UOM/fraction/LOV rules | Official masters unavailable; no compliance claim | LIMITED |
| Delivery contract | Exact 252 headers and row width validated structurally | PASS |
| Scalability/cost | Five-row diagnostic was not externally executed | NOT_VALIDATED |

## 7. Delivery-schema coverage

Current structural coverage counts: {'SUPPORTED': 13, 'PARTIALLY_SUPPORTED': 179, 'UNSUPPORTED_OR_DEFERRED': 60, 'UNKNOWN': 0}. Supported fields are mappings already represented by ProductTruth/raw input; partial fields require evidence or later composition; unsupported/deferred fields must not be fabricated.

## 8. Limitations and recommendation

`GROUND_TRUTH_200_UNAVAILABLE` and `REFERENCE_DATA_LIMITATION` remain in force. No field-level accuracy, LOV compliance, cost, latency, source discovery, or evidence-extraction success is claimed.

Recommendation: **B — NEEDS TARGETED FIX BEFORE PHASE 7**. Implement the minimum Phase 5→6 composition seam, add integration tests, obtain/authorize the necessary runtime sources, and rerun this exact five-row experiment. Do not start Phase 7 based on the current evidence.
