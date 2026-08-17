"""Run UNILOG Product Validation Harness and output structured evaluation reports."""

from __future__ import annotations

import json
from pathlib import Path

from unilog_product_intelligence.application.evaluation import (
    DatasetSampler,
    EvaluationReporter,
    ProductValidationHarness,
)


def main() -> None:
    root_dir = Path(__file__).resolve().parent.parent
    input_csv = root_dir / "Unihack_ Sample Dataset - Input.csv"
    docs_dir = root_dir / "docs" / "research"
    docs_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading and classifying dataset from {input_csv}...")
    sampler = DatasetSampler(input_csv)
    print(f"Total records parsed: {len(sampler.records)}")
    print(f"Distinct categories mapped: {len(sampler.category_distribution)}")

    harness = ProductValidationHarness()

    # 1. OFFLINE EVALUATION: Tier 1 (25 rows) + Tier 2 (75 rows)
    tier1_records = sampler.select_tier1()
    tier2_records = sampler.select_tier2()
    print(f"\n--- Running Offline Evaluation on Tier 1 ({len(tier1_records)} rows) ---")

    # Construct offline mock pool for known product pages in Tier 1
    mock_pool: dict[str, bytes] = {
        "https://diablotools.com/products/DCB518ASTS06G": (
            b"<html><head><title>Diablo DCB518ASTS06G Sanding Belt</title></head>"
            b"<body><h1>Diablo DCB518ASTS06G</h1><p>Part Number: DCB518ASTS06G</p>"
            b"<span class='brand'>Diablo</span>"
            b"<span class='manufacturer'>Freud Inc</span></body></html>"
        ),
        "https://diablotools.com/products/DBD090094101F": (
            b"<html><head><title>Diablo DBD090094101F Metal Cut-Off</title></head>"
            b"<body><h1>Diablo DBD090094101F</h1><p>Part Number: DBD090094101F</p>"
            b"<span class='brand'>Diablo</span></body></html>"
        ),
        "https://www.milwaukeetool.com/Products/49-94-0013": (
            b"<html><head><title>Milwaukee 49-94-0013 Cut Off Disc</title></head>"
            b"<body><h1>Milwaukee 49-94-0013</h1><p>Part Number: 49-94-0013</p>"
            b"<span class='brand'>Milwaukee</span></body></html>"
        ),
        "https://festoolusa.com/products/575306": (
            b"<html><head><title>Festool Product</title></head>"
            b"<body><h1>Festool</h1><p>Part Number: 575306</p></body></html>"
        ),
    }

    tier2_traces = []
    for r in tier2_records:
        trace = harness.evaluate_product(r, live_network=False, html_pool=mock_pool)
        tier2_traces.append(trace)

    reporter = EvaluationReporter(tier2_traces, sampler)
    summary = reporter.compute_summary()
    markdown_report = reporter.generate_markdown_report(summary)

    # 2. CONTROLLED LIVE EVALUATION: Row 2 live test
    print("\n--- Running Controlled Live Retrieval Test on Row 2 ---")
    row2_record = sampler.records[0]  # Row 1 in list (DCB518ASTS06G)
    try:
        live_trace = harness.evaluate_product(row2_record, live_network=True)
        print(f"Live Row 2 Result: Status={live_trace.final_status}, "
              f"Domain={live_trace.phase5.domain}, "
              f"Verified={live_trace.phase5.source_verified}, "
              f"IdentityScore={live_trace.phase5.identity_score}, "
              f"FetchedURLs={live_trace.phase5.urls_fetched}")
    except Exception as e:
        print(f"Live Row 2 Failed with environment exception: {e}")

    # Write output files
    summary_json_path = docs_dir / "evaluation-summary.json"
    summary_md_path = docs_dir / "evaluation-summary.md"
    traces_json_path = docs_dir / "evaluation-traces.json"

    with summary_json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote summary JSON to {summary_json_path}")

    with summary_md_path.open("w", encoding="utf-8") as f:
        f.write(markdown_report)
    print(f"Wrote summary Markdown to {summary_md_path}")

    traces_data = [t.model_dump(mode="json") for t in tier2_traces]
    with traces_json_path.open("w", encoding="utf-8") as f:
        json.dump(traces_data, f, indent=2)
    print(f"Wrote execution traces JSON to {traces_json_path}")

    print("\n=== EVALUATION HARNESS COMPLETE ===")


if __name__ == "__main__":
    main()
