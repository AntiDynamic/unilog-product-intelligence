"""Unit tests for the UNILOG Product Validation & Evaluation Harness."""

from __future__ import annotations

from pathlib import Path

from unilog_product_intelligence.application.evaluation import (
    DatasetRecord,
    DatasetSampler,
    DeterministicEvaluationProvider,
    EvaluationReporter,
    ProductValidationHarness,
)


def test_deterministic_provider_responses() -> None:
    provider = DeterministicEvaluationProvider()
    from unilog_product_intelligence.providers.base import LLMRequest

    r1 = provider.generate(LLMRequest(task="product_understanding", input_text="test"))
    assert "Industrial Tool / Supply" in r1.output_text

    r2 = provider.generate(LLMRequest(task="classification", input_text="test"))
    assert "Tools" in r2.output_text

    r3 = provider.generate(LLMRequest(task="attribute_extraction", input_text="test"))
    assert "attributes" in r3.output_text

    r4 = provider.generate(LLMRequest(task="evidence_grounded_enrichment", input_text="test"))
    assert "candidates" in r4.output_text


def test_dataset_sampler_and_categorization() -> None:
    input_csv = Path(__file__).resolve().parent.parent / "Unihack_ Sample Dataset - Input.csv"
    if not input_csv.exists():
        return

    sampler = DatasetSampler(input_csv)
    assert len(sampler.records) == 1000
    assert len(sampler.category_distribution) > 10

    tier1 = sampler.select_tier1()
    assert len(tier1) == 25

    tier2 = sampler.select_tier2()
    assert len(tier2) == 75


def test_product_validation_harness_offline_execution() -> None:
    record = DatasetRecord(
        row_number=1,
        mpn="DCB518ASTS06G",
        description="DCB518ASTS06G Diablo Sanding Belt",
        e1_brand="-- Unbranded --",
        unilog_brand="-- No Unilog Brand --",
        dib_brand="Diablo",
        manufacturer="Freud Inc",
        effective_brand="Diablo",
        categories=["A. Known manufacturer + obvious MPN"],
    )

    mock_pool = {
        "https://diablotools.com/products/DCB518ASTS06G": (
            b"<html><body><h1>Diablo DCB518ASTS06G</h1>"
            b"<p>Part Number: DCB518ASTS06G</p></body></html>"
        )
    }

    harness = ProductValidationHarness()
    trace = harness.evaluate_product(record, live_network=False, html_pool=mock_pool)

    assert trace.mpn == "DCB518ASTS06G"
    assert trace.execution_mode == "OFFLINE"
    assert trace.phase4.status in ("candidates_accepted", "understood")
    assert trace.final_status in ("REVIEW_REQUIRED", "READY_ENRICHED", "BLOCKED")


def test_evaluation_reporter_computation() -> None:
    input_csv = Path(__file__).resolve().parent.parent / "Unihack_ Sample Dataset - Input.csv"
    sampler = DatasetSampler(input_csv) if input_csv.exists() else DatasetSampler()

    record = DatasetRecord(
        row_number=1,
        mpn="DCB518ASTS06G",
        description="DCB518ASTS06G Diablo Sanding Belt",
        e1_brand="",
        unilog_brand="",
        dib_brand="Diablo",
        manufacturer="Freud Inc",
        effective_brand="Diablo",
        categories=["A. Known manufacturer + obvious MPN"],
    )

    harness = ProductValidationHarness()
    trace = harness.evaluate_product(record, live_network=False)

    reporter = EvaluationReporter([trace], sampler)
    summary = reporter.compute_summary()
    assert summary["total_products_evaluated"] == 1
    assert "retrieval_metrics" in summary
    assert "output_quality_metrics" in summary
    assert summary["output_quality_metrics"]["invention_rate"] == 0.0

    md = reporter.generate_markdown_report(summary)
    assert "# UNILOG Product Validation & Testing Report" in md
    assert "Invention Rate" in md
