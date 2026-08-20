"""Unit tests for the Live Retrieval Benchmark Engine."""

from __future__ import annotations

import json
from pathlib import Path

from unilog_product_intelligence.application.live_benchmark import (
    LiveBenchmarkManifestItem,
    LiveBenchmarkReporter,
    LiveBenchmarkRunner,
    LiveExecutionTrace,
)


def test_manifest_validation() -> None:
    manifest_path = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "research"
        / "live-benchmark-manifest.json"
    )
    if not manifest_path.exists():
        return

    with manifest_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    assert len(raw) == 30
    items = [LiveBenchmarkManifestItem.model_validate(x) for x in raw]
    assert len(items) == 30
    assert items[0].mpn == "DCB518ASTS06G"


def test_live_benchmark_runner_and_reporter() -> None:
    item = LiveBenchmarkManifestItem(
        input_row=2,
        data_row_index=1,
        mpn="DCB518ASTS06G",
        part_manuf="Freud Inc (2435)",
        e1_brand="-- Unbranded --",
        unilog_brand="-- No Unilog Brand --",
        dib_brand="-- No DIB Brand --",
        description='DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc',
        category="Known manufacturer + obvious MPN / Standard direct URL candidate",
    )

    runner = LiveBenchmarkRunner(timeout=4.0)
    trace = runner.run_item(item)

    assert isinstance(trace, LiveExecutionTrace)
    assert trace.row_number == 2
    assert trace.input.mpn == "DCB518ASTS06G"
    assert trace.final.status in ("READY", "REVIEW_REQUIRED", "BLOCKED")

    reporter = LiveBenchmarkReporter([trace])
    summary = reporter.compute_summary()
    assert summary["total_products_benchmarked"] == 1
    assert "overall_metrics" in summary
    assert summary["overall_metrics"]["manufacturer_resolution_rate"] == 1.0

    report = reporter.generate_markdown_report(summary)
    assert "# UNILOG Live Retrieval Benchmark Report" in report
    assert "Row 2 End-to-End Deep Dive" in report
