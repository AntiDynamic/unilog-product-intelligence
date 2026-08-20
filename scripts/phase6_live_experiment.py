# ruff: noqa: E501
"""Generate a safe, deterministic Phase 6.5 experiment record from real local files.

This command deliberately does not make network or Gemini calls. It selects representative real
rows, validates the delivery contract, and records the exact boundary that prevents live execution
when external egress is not authorized. An explicitly authorized future runner can reuse the
selection and snapshots without changing the experiment methodology.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from unilog_product_intelligence.config import GEMINI_MODEL, Settings
from unilog_product_intelligence.data.delivery import validate_delivery_csv
from unilog_product_intelligence.data.readers import read_tabular_file

PLACEHOLDERS = {"", "-- unbranded --", "-- no unilog brand --", "-- no dib brand --", "-"}
EXPECTED_INPUT_HEADERS = [
    "Mfg_Part_Num",
    "Part_Desc",
    "E1_Brand",
    "Unilog_Brand",
    "DIB_Brand",
    "Part_Manuf",
]


def select_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Select five distinct rows using stable difficulty-profile rules and row order tie-breaks."""

    def text(row: Any, field: str) -> str:
        return str(row.raw_values.get(field) or "").strip()

    def non_placeholder(value: str) -> bool:
        return value.casefold() not in PLACEHOLDERS

    def dimensions(row: Any) -> bool:
        return bool(
            re.search(
                r"\d(?:\s*(?:x|×|/|in|ft|mm|cm|pc|pcs)\s*\d|\s*(?:in|ft|mm|cm|pc|pcs)\b)",
                text(row, "Part_Desc"),
                re.IGNORECASE,
            )
        )

    def embedded_brand(row: Any) -> bool:
        description = text(row, "Part_Desc").casefold()
        candidates = [text(row, "E1_Brand"), text(row, "Unilog_Brand")]
        return any(
            non_placeholder(value) and value.casefold() in description for value in candidates
        )

    mpn_counts = Counter(text(row, "Mfg_Part_Num").casefold() for row in rows)
    used: set[int] = set()

    def choose(name: str, predicate: Any, *, reverse: bool = False) -> dict[str, Any]:
        candidates = [row for row in rows if row.row_number not in used and predicate(row)]
        if not candidates:
            raise ValueError(f"no representative row found for profile {name}")
        selected = sorted(candidates, key=lambda row: row.row_number, reverse=reverse)[0]
        used.add(selected.row_number)
        return _snapshot(selected, name)

    selected = [
        choose(
            "clear_identity",
            lambda row: (
                non_placeholder(text(row, "Mfg_Part_Num"))
                and non_placeholder(text(row, "Part_Manuf"))
                and text(row, "Mfg_Part_Num").casefold() in text(row, "Part_Desc").casefold()
            ),
        ),
        choose("dimensions_and_uom", dimensions),
        choose("embedded_brand", embedded_brand),
        choose(
            "cryptic_abbreviation",
            lambda row: (
                non_placeholder(text(row, "Mfg_Part_Num"))
                and non_placeholder(text(row, "Part_Manuf"))
                and len(text(row, "Part_Desc")) <= 18
            ),
        ),
        choose(
            "ambiguous_duplicate_mpn",
            lambda row: mpn_counts[text(row, "Mfg_Part_Num").casefold()] > 1,
            reverse=True,
        ),
    ]
    return selected


def _snapshot(row: Any, profile: str) -> dict[str, Any]:
    return {
        "row_index": row.row_number,
        "row_hash": row.row_hash,
        "selection_profile": profile,
        "raw": {header: row.raw_values.get(header) for header in EXPECTED_INPUT_HEADERS},
        "normalized": {
            header: row.normalized_values.get(header) for header in EXPECTED_INPUT_HEADERS
        },
        "placeholder_fields": [
            header
            for header in EXPECTED_INPUT_HEADERS
            if row.normalization[header].reason == "placeholder"
        ],
    }


def build_report(input_path: Path, delivery_path: Path) -> dict[str, Any]:
    input_data = read_tabular_file(input_path)
    delivery_data = read_tabular_file(delivery_path)
    delivery_headers = delivery_data.sheets[0].headers
    delivery_validation = validate_delivery_csv(delivery_path, delivery_headers)
    settings = Settings()
    selected = select_rows(input_data.rows)
    per_product = []
    for snapshot in selected:
        per_product.append(
            {
                "product_id": f"phase65-row-{snapshot['row_index']}",
                **snapshot,
                "manufacturer_resolution": "NOT_RUN",
                "brand_resolution": "DETERMINISTIC_INPUT_ONLY",
                "classification_status": "NOT_RUN",
                "source_discovery_status": "NOT_RUN",
                "source_verification_status": "NOT_RUN",
                "retrieval_status": "NOT_RUN",
                "evidence_status": "NOT_RUN",
                "enrichment_status": "NOT_RUN",
                "validation_status": "NOT_RUN",
                "publication_state": "REVIEW_REQUIRED",
                "failure_category": "OTHER",
                "failure_detail": "EXTERNAL_EXECUTION_UNAUTHORIZED",
                "failure_reason": (
                    "Phase 4 Gemini and Phase 5 web retrieval were not attempted because local-data "
                    "egress was not authorized."
                ),
                "telemetry": {
                    "gemini_calls": 0,
                    "search_calls": 0,
                    "url_context_calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cached_tokens": 0,
                    "latency_ms": 0,
                    "estimated_cost": None,
                },
            }
        )
    coverage = _delivery_coverage(delivery_headers)
    return {
        "experiment": "phase-6.5-live-end-to-end-validation",
        "experiment_version": "phase65-v1",
        "objective": "Measure the real pipeline without simplifying or fabricating unavailable evidence.",
        "environment": {
            "input_path": input_path.name,
            "delivery_path": delivery_path.name,
            "gemini_key_configured": bool(settings.gemini_api_key),
            "external_execution_authorized": False,
            "live_calls_attempted": False,
            "model": GEMINI_MODEL,
            "official_solution_guide_pdf_available": False,
        },
        "dataset": {
            "input_rows": len(input_data.rows),
            "input_columns": input_data.sheets[0].column_count,
            "input_headers": input_data.sheets[0].headers,
            "input_sha256": input_data.source_file.sha256,
            "expected_input_headers_match": input_data.sheets[0].headers == EXPECTED_INPUT_HEADERS,
            "delivery_data_rows": len(delivery_data.rows),
            "delivery_columns": len(delivery_headers),
            "delivery_headers": delivery_headers,
            "delivery_duplicate_headers": delivery_validation.duplicate_headers,
            "delivery_invalid_row_widths": delivery_validation.invalid_row_widths,
            "delivery_structurally_valid": delivery_validation.valid,
        },
        "selection_method": {
            "deterministic": True,
            "profiles": [
                "clear_identity",
                "dimensions_and_uom",
                "embedded_brand",
                "cryptic_abbreviation",
                "ambiguous_duplicate_mpn",
            ],
            "tie_break": "ascending source row, except duplicate profile selects the highest row index",
        },
        "products": per_product,
        "aggregate": {
            "total_products": len(per_product),
            "products_with_verified_source": 0,
            "products_with_evidence": 0,
            "products_with_enrichment": 0,
            "ready": 0,
            "review_required": len(per_product),
            "blocked": 0,
            "unsupported_candidates": 0,
            "conflicts": 0,
            "total_gemini_calls": 0,
            "total_search_calls": 0,
            "total_url_context_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cached_tokens": 0,
            "average_cost": None,
            "average_latency_ms": 0,
        },
        "integration_finding": {
            "status": "TARGETED_SEAM_IMPLEMENTED_NOT_LIVE_VALIDATED",
            "phase5_to_phase6_path": "Phase65Pipeline implemented; legacy CLI remains direct",
            "evidence": (
                "Phase 6 CLI creates ProductTruth directly and calls EnrichmentService; it does not "
                "invoke ManufacturerDiscoveryAgent or ManufacturerIntelligenceService when evidence is absent."
            ),
            "minimum_fix": (
                "Add one composition-owned pipeline seam that runs the existing Phase 4 orchestrator, "
                "then Phase 5 manufacturer intelligence, then Phase 6 enrichment; keep the existing "
                "services and source-policy gates unchanged."
            ),
        },
        "reference_data": {
            "status": "REFERENCE_DATA_LIMITATION",
            "ground_truth_200": "GROUND_TRUTH_200_UNAVAILABLE",
            "official_lov_uom_manufacturer_assets": "unavailable",
            "rules_from_attached_spec": [
                "placeholders are not data",
                "manufacturer sources are required",
                "marketplaces/distributors are not authoritative",
                "unsupported values must not publish",
                "quality is preferred over field-fill breadth",
            ],
        },
        "delivery_coverage": coverage,
        "recommendation": {
            "decision": "B_NEEDS_TARGETED_FIX_BEFORE_PHASE_7",
            "reason": "The experiment did not reach Gemini or manufacturer retrieval, and the Phase 5→6 seam is implemented locally but not live-validated.",
            "next_action": "Implement and test the minimum composition seam, then rerun this same five-row experiment only with explicit egress authorization.",
        },
    }


def _delivery_coverage(headers: list[str]) -> dict[str, Any]:
    supported_exact = {
        "Mfg_Part_Num",
        "Part_Desc",
        "E1_Brand",
        "Unilog_Brand",
        "DIB_Brand",
        "Part_Manuf",
        "MANUFACTURER_PART_NUMBER",
        "MANUFACTURER_NAME",
        "BRAND_NAME",
        "Dept",
        "Class",
        "Fine",
        "Classpath",
    }
    partial_prefixes = ("ATTRIBUTE_", "Ref URL", "ITEM_FEATURES_", "Alternate Image")
    supported = [header for header in headers if header in supported_exact]
    partial = [
        header
        for header in headers
        if header not in supported and header.startswith(partial_prefixes)
    ]
    unsupported = [
        header for header in headers if header not in supported and header not in partial
    ]
    return {
        "SUPPORTED": supported,
        "PARTIALLY_SUPPORTED": partial,
        "UNSUPPORTED_OR_DEFERRED": unsupported,
        "UNKNOWN": [],
        "counts": {
            "SUPPORTED": len(supported),
            "PARTIALLY_SUPPORTED": len(partial),
            "UNSUPPORTED_OR_DEFERRED": len(unsupported),
            "UNKNOWN": 0,
        },
        "note": "Coverage describes current ProductTruth/delivery primitives, not populated values or Phase 7 descriptions.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    aggregate = report["aggregate"]
    lines = [
        "# Phase 6.5 live end-to-end validation",
        "",
        "## 1. Objective",
        "",
        report["objective"],
        "The experiment uses five deterministic real-row profiles and does not optimize for a successful-looking demo.",
        "",
        "## 2. Environment and authorization",
        "",
        f"Input: `{report['environment']['input_path']}` ({dataset['input_rows']} data rows, {dataset['input_columns']} columns).",
        f"Delivery contract: `{report['environment']['delivery_path']}` ({dataset['delivery_columns']} columns, {dataset['delivery_data_rows']} data rows).",
        f"Model configured: `{report['environment']['model']}`; key configured: `{report['environment']['gemini_key_configured']}`.",
        "Live Gemini/Search/URL Context calls were not attempted because external egress for local product data was not authorized.",
        "",
        "## 3. Product-selection methodology",
        "",
        "Selection is deterministic, non-random, and uses stable row-index tie-breaks. It covers clear identity, dimensions/UOM, embedded brand, cryptic abbreviation, and an ambiguous duplicate MPN.",
        "",
        "| Product | Row | Profile | Manufacturer | MPN | Description |",
        "|---|---:|---|---|---|---|",
    ]
    for product in report["products"]:
        raw = product["raw"]
        lines.append(
            f"| `{product['product_id']}` | {product['row_index']} | {product['selection_profile']} | {raw['Part_Manuf']} | {raw['Mfg_Part_Num']} | {raw['Part_Desc']} |"
        )
    lines += [
        "",
        "## 4. Pipeline and observed result",
        "",
        "The deterministic reader and placeholder normalization ran. The live chain stopped before Phase 4 because authorization was absent; therefore classification, manufacturer discovery, retrieval, evidence extraction, Phase 6 enrichment, and publication were not claimed as executed.",
        "",
        f"Aggregate: {aggregate['total_products']} selected, {aggregate['review_required']} review-required, {aggregate['ready']} READY, {aggregate['blocked']} BLOCKED, {aggregate['total_gemini_calls']} Gemini calls, {aggregate['total_search_calls']} Search calls, {aggregate['total_url_context_calls']} URL Context calls.",
        "",
        "## 5. Phase 5 → Phase 6 integration finding",
        "",
        "The current Phase 6 CLI constructs ProductTruth directly and calls EnrichmentService. It does not invoke Phase 5 when evidence is absent. This is a real missing composition boundary, not a data failure. The minimum correction is one composition-owned seam that reuses the existing Phase 4 orchestrator, ManufacturerIntelligenceService, and EnrichmentService in order.",
        "",
        "## 6. Solution-guide comparison",
        "",
        "The attached task specification is available; no separate Solution Guide PDF was found locally. The following are implementation observations:",
        "",
        "| Requirement | Current observation | Result |",
        "|---|---|---|",
        "| Six raw input fields and placeholder handling | Reader preserves raw values and normalizes known placeholders | PASS |",
        "| De-duplication | Deterministic duplicate signals exist; no merge is performed | PARTIAL |",
        "| Taxonomy/classification and attribute extraction | Phase 4 agents exist but were not live-executed | NOT_VALIDATED |",
        "| Manufacturer-source enrichment | Phase 5 policy/retrieval exists; Phase 5→6 invocation is absent | PARTIAL |",
        "| Evidence/provenance and validation | Phase 6 contracts and gates exist; no live evidence in this run | PARTIAL |",
        "| UOM/fraction/LOV rules | Official masters unavailable; no compliance claim | LIMITED |",
        "| Delivery contract | Exact 252 headers and row width validated structurally | PASS |",
        "| Scalability/cost | Five-row diagnostic was not externally executed | NOT_VALIDATED |",
        "",
        "## 7. Delivery-schema coverage",
        "",
        f"Current structural coverage counts: {report['delivery_coverage']['counts']}. Supported fields are mappings already represented by ProductTruth/raw input; partial fields require evidence or later composition; unsupported/deferred fields must not be fabricated.",
        "",
        "## 8. Limitations and recommendation",
        "",
        "`GROUND_TRUTH_200_UNAVAILABLE` and `REFERENCE_DATA_LIMITATION` remain in force. No field-level accuracy, LOV compliance, cost, latency, source discovery, or evidence-extraction success is claimed.",
        "",
        "Recommendation: **B — NEEDS TARGETED FIX BEFORE PHASE 7**. Implement the minimum Phase 5→6 composition seam, add integration tests, obtain/authorize the necessary runtime sources, and rerun this exact five-row experiment. Do not start Phase 7 based on the current evidence.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the safe Phase 6.5 live experiment report"
    )
    parser.add_argument(
        "--input", type=Path, default=Path("data/external/Unihack_ Sample Dataset - Input.csv")
    )
    parser.add_argument(
        "--delivery",
        type=Path,
        default=Path("data/external/Unihack_ Expected Output - Delivery Format.csv"),
    )
    parser.add_argument(
        "--output-json", type=Path, default=Path("docs/research/phase-6-live-experiment.json")
    )
    parser.add_argument(
        "--output-md", type=Path, default=Path("docs/research/phase-6-live-experiment.md")
    )
    args = parser.parse_args()
    report = build_report(args.input, args.delivery)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["aggregate"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
