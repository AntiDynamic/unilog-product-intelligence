"""Execute Controlled Live Retrieval Benchmark against real industrial dataset."""

from __future__ import annotations

import json
import time
from pathlib import Path

from unilog_product_intelligence.application.live_benchmark import (
    LiveBenchmarkManifestItem,
    LiveBenchmarkReporter,
    LiveBenchmarkRunner,
    LiveExecutionTrace,
)


def main() -> None:
    root_dir = Path(__file__).resolve().parent.parent
    manifest_path = root_dir / "docs" / "research" / "live-benchmark-manifest.json"

    if not manifest_path.exists():
        print(f"Error: Manifest {manifest_path} not found.")
        return

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest_raw = json.load(f)

    manifest_items = [LiveBenchmarkManifestItem.model_validate(item) for item in manifest_raw]
    print(f"Loaded {len(manifest_items)} manifest records for Live Retrieval Benchmark.")
    print("Beginning LIVE INTERNET execution (real HTTP sockets)...\n")

    runner = LiveBenchmarkRunner(timeout=6.0)
    traces: list[LiveExecutionTrace] = []

    for i, item in enumerate(manifest_items, start=1):
        print(
            f"[{i}/{len(manifest_items)}] Testing Row {item.input_row}: "
            f"MPN={item.mpn}, Manuf={item.part_manuf}, Brand={item.dib_brand or item.e1_brand}..."
        )
        t_start = time.perf_counter()
        trace = runner.run_item(item)
        dur = round((time.perf_counter() - t_start) * 1000)
        print(
            f"   -> Status: {trace.final.status}, "
            f"Domain: {trace.resolution.resolved_domain or 'None'}, "
            f"HTTP Requests: {trace.final.total_http_requests}, "
            f"IdentityScore: {trace.verification.identity_score:.2f}, "
            f"Duration: {dur}ms"
        )
        traces.append(trace)

    reporter = LiveBenchmarkReporter(traces)
    summary = reporter.compute_summary()
    markdown_report = reporter.generate_markdown_report(summary)

    # Write output artifacts
    summary_json_path = root_dir / "docs" / "research" / "live-benchmark-summary.json"
    with summary_json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote summary JSON to {summary_json_path}")

    summary_md_path = root_dir / "docs" / "research" / "live-benchmark-summary.md"
    with summary_md_path.open("w", encoding="utf-8") as f:
        f.write(markdown_report)
    print(f"Wrote summary Markdown to {summary_md_path}")

    traces_json_path = root_dir / "docs" / "research" / "live-benchmark-traces.json"
    with traces_json_path.open("w", encoding="utf-8") as f:
        json.dump([t.model_dump() for t in traces], f, indent=2)
    print(f"Wrote execution traces JSON to {traces_json_path}")

    print("\n=== LIVE BENCHMARK COMPLETE ===")


if __name__ == "__main__":
    main()
