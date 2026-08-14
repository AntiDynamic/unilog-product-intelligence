"""Phase 6 CLI for deterministic diagnostics and bounded real-data runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unilog_product_intelligence.application.execution import GeminiExecutionService
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.config import Settings
from unilog_product_intelligence.data.readers import read_tabular_file
from unilog_product_intelligence.domain.truth import Source, SourceAuthority, SourceType
from unilog_product_intelligence.providers.gemini import GeminiProvider

from .agent import EvidenceGroundedEnrichmentAgent
from .models import EnrichmentResult
from .planner import AttributePlanner, ReferencePack
from .service import EnrichmentService


def phase6_main() -> None:
    parser = argparse.ArgumentParser(description="Run evidence-grounded Phase 6 enrichment.")
    parser.add_argument("--input", required=True, help="CSV/XLSX raw UniHack input")
    parser.add_argument("--limit", type=int, default=3, help="Maximum real rows to process")
    parser.add_argument("--row-id", action="append", help="Specific 1-based data row(s)")
    parser.add_argument("--output", help="Optional JSON diagnostics output path")
    parser.add_argument(
        "--live", action="store_true", help="Enable Gemini only when evidence exists"
    )
    parser.add_argument(
        "--reference-root", action="append", default=[], help="Reference search root"
    )
    args = parser.parse_args()
    input_path = Path(args.input)
    tabular = read_tabular_file(input_path)
    indexes = (
        [int(value) for value in args.row_id]
        if args.row_id
        else list(range(1, min(args.limit, len(tabular.rows)) + 1))
    )
    roots = [Path.cwd(), *[Path(value) for value in args.reference_root]]
    reference_pack = ReferencePack.discover(roots)
    settings = Settings()
    provider = (
        GeminiExecutionService(GeminiProvider(settings))
        if args.live and settings.gemini_api_key
        else None
    )
    service = EnrichmentService(
        planner=AttributePlanner(reference_pack=reference_pack),
        agent=EvidenceGroundedEnrichmentAgent(provider=provider),
    )
    truth_service = ProductTruthService()
    results: list[EnrichmentResult] = []
    for data_index in indexes:
        if data_index < 1 or data_index > len(tabular.rows):
            raise ValueError(f"row-id {data_index} is outside 1..{len(tabular.rows)}")
        row = tabular.rows[data_index - 1]
        product = truth_service.create_from_raw_input(
            product_id=f"unihack-row-{row.row_number}",
            raw_values=row.raw_values,
            source=Source(
                source_id=f"input-{tabular.source_file.sha256 or 'unknown'}",
                source_type=SourceType.SUPPLIED_INPUT,
                authority=SourceAuthority.MEDIUM,
                uri=str(input_path.resolve()),
            ),
        )
        results.append(service.enrich(product))
    payload = {
        "phase": 6,
        "input": str(input_path),
        "reference_availability": reference_pack.availability,
        "reference_files": {name: str(path) for name, path in reference_pack.files.items()},
        "live_requested": args.live,
        "gemini_key_configured": bool(settings.gemini_api_key),
        "rows_requested": indexes,
        "results": [result.model_dump(mode="json") for result in results],
        "summary": _summary(results),
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


def _summary(results: list[EnrichmentResult]) -> dict[str, int]:
    return {
        "products": len(results),
        "agent_calls": sum(result.metrics.agent_calls for result in results),
        "ready": sum(result.metrics.ready for result in results),
        "review_required": sum(result.metrics.review_required for result in results),
        "blocked": sum(result.metrics.blocked for result in results),
        "candidates": sum(len(result.candidates) for result in results),
        "conflicts": sum(result.metrics.conflicts for result in results),
    }


if __name__ == "__main__":
    phase6_main()
