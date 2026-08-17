# ruff: noqa: E501
"""Unit tests for the evaluation harness (scripts/evaluate_delivery_50.py).

Validates that all benchmark metrics are strictly measured, that no metrics are
unconditionally hardcoded or faked, and that ground truth, domain authority,
MPN integrity, and taxonomy depth are evaluated rigorously.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.evaluate_delivery_50 import (
    classify_mpn_match,
    evaluate,
    get_classpath_depth,
)


def test_classify_mpn_match_exact() -> None:
    """Exact MPN match returns EXACT."""
    assert classify_mpn_match("ABC123", "ABC123") == "EXACT"
    assert classify_mpn_match("  48-00-5184 ", "48-00-5184") == "EXACT"


def test_classify_mpn_match_normalized_equivalent() -> None:
    """Normalized match returns NORMALIZED_EQUIVALENT when punctuation/case differ."""
    assert classify_mpn_match("48-00-5184", "48005184") == "NORMALIZED_EQUIVALENT"
    assert classify_mpn_match("dcb518asts06g", "DCB518ASTS06G") == "NORMALIZED_EQUIVALENT"
    assert classify_mpn_match("ABC 123", "abc-123") == "NORMALIZED_EQUIVALENT"


def test_classify_mpn_match_different_no_substring_collision() -> None:
    """TEST D: ABC123 must NOT match ABC1234; substring collisions must return DIFFERENT."""
    assert classify_mpn_match("ABC123", "ABC1234") == "DIFFERENT"
    assert classify_mpn_match("ABC1234", "ABC123") == "DIFFERENT"
    assert classify_mpn_match("48-00-5184", "48-00-5185") == "DIFFERENT"


def test_classify_mpn_match_missing() -> None:
    """Empty or missing generated MPN returns MISSING."""
    assert classify_mpn_match("ABC123", "") == "MISSING"
    assert classify_mpn_match("ABC123", "   ") == "MISSING"


def test_get_classpath_depth() -> None:
    """TEST F: Classpath depth is correctly measured from delimiter segments."""
    assert get_classpath_depth("Tools > Power Tools > Drills") == 3
    assert get_classpath_depth("Appliances & Consumer Electronics>Kitchen Appliances>Built-In Dishwashers") == 3
    assert get_classpath_depth("Hardware") == 1
    assert get_classpath_depth("") == 0
    assert get_classpath_depth("   ") == 0


def test_row_with_no_domain_resolution_does_not_increment_domain_resolved(tmp_path: Path) -> None:
    """TEST A: A row with no domain resolution must NOT increment domain_resolved or verified_domain."""
    input_csv = tmp_path / "input.csv"
    output_csv = tmp_path / "output.csv"
    schema_json = tmp_path / "schema.json"
    expected_csv = tmp_path / "expected.csv"

    # Input with unknown manufacturer
    with input_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Mfg_Part_Num", "Part_Manuf", "Part_Desc"])
        writer.writerow(["UNKNOWN-123", "Completely Unknown Corp", "Some Item"])

    # Output with no URL and unresolvable domain
    headers = [
        "MFR URL", "Ref URL 1", "Ref URL 2", "Ref URL 3", "Ref URL 4", "Ref URL 5",
        "PART_NUMBER", "Dept", "Class", "Fine", "SKU - MY_PART_NUMBER", "Mfg_Part_Num",
        "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf",
        "MANUFACTURER_NAME", "BRAND_NAME", "TRADE_NAME", "MANUFACTURER_PART_NUMBER",
        "ALTERNATE_PART_NUMBER", "Classpath", "SHORT_DESC", "LONG_DESC1"
    ]
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow([""] * len(headers))

    with schema_json.open("w", encoding="utf-8") as f:
        json.dump({"headers": headers}, f)

    with expected_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

    report = evaluate(
        input_path=input_csv,
        output_path=output_csv,
        expected_path=expected_csv,
        schema_path=schema_json,
        traces_path=None,
    )

    rm = report["retrieval_metrics"]
    assert rm["verified_domain_count"] == 0
    assert rm["verified_domain_rate_pct"] == 0.0
    assert rm["verified_source_found_count"] == 0
    assert rm["authoritative_source_rate_pct"] == 0.0


def test_candidate_domain_not_counted_as_verified_domain(tmp_path: Path) -> None:
    """TEST B: A candidate domain must NOT count as a verified domain."""
    input_csv = tmp_path / "input.csv"
    output_csv = tmp_path / "output.csv"
    schema_json = tmp_path / "schema.json"
    expected_csv = tmp_path / "expected.csv"
    traces_json = tmp_path / "traces.json"

    headers = [
        "MFR URL", "Ref URL 1", "Ref URL 2", "Ref URL 3", "Ref URL 4", "Ref URL 5",
        "PART_NUMBER", "Dept", "Class", "Fine", "SKU - MY_PART_NUMBER", "Mfg_Part_Num",
        "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf",
        "MANUFACTURER_NAME", "BRAND_NAME", "TRADE_NAME", "MANUFACTURER_PART_NUMBER",
        "ALTERNATE_PART_NUMBER", "Classpath", "SHORT_DESC", "LONG_DESC1"
    ]

    with input_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Mfg_Part_Num", "Part_Manuf", "Part_Desc"])
        writer.writerow(["ITEM-1", "Candidate Only Corp", "Item"])

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow([""] * len(headers))

    with schema_json.open("w", encoding="utf-8") as f:
        json.dump({"headers": headers}, f)

    with expected_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

    # Trace with candidate domain ONLY (no verified domains)
    with traces_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "execution_mode": "deterministic",
                "traces": [
                    {
                        "row_number": 2,
                        "domain_candidates": [
                            {"domain": "candidate.example.com", "status": "candidate_manufacturer_source", "source": "search", "reason": "candidate"}
                        ],
                        "verified_domains": [],
                        "source_status": "not_found",
                    }
                ],
            },
            f,
        )

    report = evaluate(
        input_path=input_csv,
        output_path=output_csv,
        expected_path=expected_csv,
        schema_path=schema_json,
        traces_path=traces_json,
    )

    rm = report["retrieval_metrics"]
    assert rm["domain_candidate_count"] == 1
    assert rm["verified_domain_count"] == 0
    assert rm["verified_domain_rate_pct"] == 0.0


def test_non_authoritative_source_not_counted_as_authoritative(tmp_path: Path) -> None:
    """TEST C: A non-authoritative marketplace/distributor source must NOT count as authoritative."""
    input_csv = tmp_path / "input.csv"
    output_csv = tmp_path / "output.csv"
    schema_json = tmp_path / "schema.json"
    expected_csv = tmp_path / "expected.csv"

    headers = [
        "MFR URL", "Ref URL 1", "Ref URL 2", "Ref URL 3", "Ref URL 4", "Ref URL 5",
        "PART_NUMBER", "Dept", "Class", "Fine", "SKU - MY_PART_NUMBER", "Mfg_Part_Num",
        "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf",
        "MANUFACTURER_NAME", "BRAND_NAME", "TRADE_NAME", "MANUFACTURER_PART_NUMBER",
        "ALTERNATE_PART_NUMBER", "Classpath", "SHORT_DESC", "LONG_DESC1"
    ]

    with input_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Mfg_Part_Num", "Part_Manuf", "Part_Desc"])
        writer.writerow(["ITEM-1", "Milwaukee", "Item"])

    # Output containing an unauthorized distributor/marketplace URL
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        row = [""] * len(headers)
        row[0] = "https://www.amazon.com/dp/B0000224"
        writer.writerow(row)

    with schema_json.open("w", encoding="utf-8") as f:
        json.dump({"headers": headers}, f)

    with expected_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

    report = evaluate(
        input_path=input_csv,
        output_path=output_csv,
        expected_path=expected_csv,
        schema_path=schema_json,
        traces_path=None,
    )

    rm = report["retrieval_metrics"]
    assert rm["candidate_source_found_count"] == 1
    assert rm["verified_source_found_count"] == 0
    assert rm["authoritative_source_rate_pct"] == 0.0


def test_missing_ground_truth_row_does_not_fabricate_accuracy(tmp_path: Path) -> None:
    """TEST E: A missing ground truth row must NOT produce a fabricated accuracy score."""
    input_csv = tmp_path / "input.csv"
    output_csv = tmp_path / "output.csv"
    schema_json = tmp_path / "schema.json"
    expected_csv = tmp_path / "expected.csv"

    headers = [
        "MFR URL", "Ref URL 1", "Ref URL 2", "Ref URL 3", "Ref URL 4", "Ref URL 5",
        "PART_NUMBER", "Dept", "Class", "Fine", "SKU - MY_PART_NUMBER", "Mfg_Part_Num",
        "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf",
        "MANUFACTURER_NAME", "BRAND_NAME", "TRADE_NAME", "MANUFACTURER_PART_NUMBER",
        "ALTERNATE_PART_NUMBER", "Classpath", "SHORT_DESC", "LONG_DESC1"
    ]

    with input_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Mfg_Part_Num", "Part_Manuf", "Part_Desc"])
        writer.writerow(["UNMATCHED-MPN", "Some Maker", "Some Item"])

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        row = [""] * len(headers)
        row[11] = "UNMATCHED-MPN"
        row[17] = "Some Maker"
        row[18] = "Some Brand"
        writer.writerow(row)

    with schema_json.open("w", encoding="utf-8") as f:
        json.dump({"headers": headers}, f)

    # Expected output CSV with different reference items
    with expected_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        ref_row = [""] * len(headers)
        ref_row[11] = "OTHER-PRODUCT-123"
        writer.writerow(ref_row)

    report = evaluate(
        input_path=input_csv,
        output_path=output_csv,
        expected_path=expected_csv,
        schema_path=schema_json,
        traces_path=None,
    )

    im = report["identity_metrics"]
    gt = report["ground_truth"]
    assert gt["ground_truth_records_available"] == 0
    assert im["manufacturer_ground_truth_accuracy_pct"] is None
    assert im["brand_ground_truth_accuracy_pct"] is None
    assert im["manufacturer_resolved_count"] == 1
    assert im["manufacturer_resolved_rate_pct"] == 100.0


def test_url_alone_does_not_count_as_valid_evidence(tmp_path: Path) -> None:
    """TEST H: A URL alone without verified source authority does NOT count as valid evidence."""
    input_csv = tmp_path / "input.csv"
    output_csv = tmp_path / "output.csv"
    schema_json = tmp_path / "schema.json"
    expected_csv = tmp_path / "expected.csv"

    headers = [
        "MFR URL", "Ref URL 1", "Ref URL 2", "Ref URL 3", "Ref URL 4", "Ref URL 5",
        "PART_NUMBER", "Dept", "Class", "Fine", "SKU - MY_PART_NUMBER", "Mfg_Part_Num",
        "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf",
        "MANUFACTURER_NAME", "BRAND_NAME", "TRADE_NAME", "MANUFACTURER_PART_NUMBER",
        "ALTERNATE_PART_NUMBER", "Classpath", "SHORT_DESC", "LONG_DESC1"
    ]

    with input_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Mfg_Part_Num", "Part_Manuf", "Part_Desc"])
        writer.writerow(["ITEM-1", "Unknown Mfr", "Item"])

    # Output with unverified URL and text
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        row = [""] * len(headers)
        row[0] = "https://unverified.example.com/product"
        row[23] = "Short Description"
        writer.writerow(row)

    with schema_json.open("w", encoding="utf-8") as f:
        json.dump({"headers": headers}, f)

    with expected_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

    report = evaluate(
        input_path=input_csv,
        output_path=output_csv,
        expected_path=expected_csv,
        schema_path=schema_json,
        traces_path=None,
    )

    em = report["evidence_metrics"]
    assert em["products_with_authoritative_evidence"] == 0
    assert em["products_with_evidence_rate_pct"] == 0.0


def test_benchmark_modes_labeled_correctly(tmp_path: Path) -> None:
    """TEST I & J: Deterministic benchmark labeled deterministic; live-gemini labeled live-gemini."""
    input_csv = tmp_path / "input.csv"
    output_csv = tmp_path / "output.csv"
    schema_json = tmp_path / "schema.json"
    expected_csv = tmp_path / "expected.csv"
    det_traces = tmp_path / "det_traces.json"
    gemini_traces = tmp_path / "gemini_traces.json"

    headers = ["MFR URL", "Mfg_Part_Num", "Part_Manuf", "MANUFACTURER_NAME", "BRAND_NAME"]

    with input_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Mfg_Part_Num", "Part_Manuf", "Part_Desc"])
        writer.writerow(["ITEM-1", "Maker", "Item"])

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow([""] * len(headers))

    with schema_json.open("w", encoding="utf-8") as f:
        json.dump({"headers": headers}, f)

    with expected_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

    with det_traces.open("w", encoding="utf-8") as f:
        json.dump({"execution_mode": "deterministic", "traces": []}, f)

    with gemini_traces.open("w", encoding="utf-8") as f:
        json.dump({"execution_mode": "live-gemini", "traces": []}, f)

    report_det = evaluate(input_path=input_csv, output_path=output_csv, expected_path=expected_csv, schema_path=schema_json, traces_path=det_traces)
    assert report_det["execution_mode"] == "deterministic"

    report_gemini = evaluate(input_path=input_csv, output_path=output_csv, expected_path=expected_csv, schema_path=schema_json, traces_path=gemini_traces)
    assert report_gemini["execution_mode"] == "live-gemini"
