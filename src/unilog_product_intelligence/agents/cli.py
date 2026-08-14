"""Bounded Phase 4 real-input execution path."""

import argparse
import json
import os
from pathlib import Path

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.config import Settings
from unilog_product_intelligence.data.readers import read_tabular_file
from unilog_product_intelligence.domain.truth import Source, SourceAuthority, SourceType
from unilog_product_intelligence.providers import GeminiProvider

from .orchestration import ProductOrchestrator


def phase4_main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded Gemini orchestration over real UniLog rows"
    )
    parser.add_argument("--input", default=os.getenv("UNILOG_INPUT_FILE"))
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--row-id", type=int)
    parser.add_argument("--prompt-version", default="v1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.input:
        print(
            json.dumps(
                {"status": "input_unavailable", "reason": "pass --input or set UNILOG_INPUT_FILE"}
            )
        )
        return 2
    path = Path(args.input)
    if not path.is_file():
        print(json.dumps({"status": "input_unavailable", "path": str(path)}))
        return 2
    rows = read_tabular_file(path).rows
    selected = [row for row in rows if args.row_id is None or row.row_number == args.row_id]
    selected = selected[: max(0, args.limit)] if args.row_id is None else selected[:1]
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "rows_selected": len(selected),
                    "row_numbers": [row.row_number for row in selected],
                }
            )
        )
        return 0
    orchestrator = ProductOrchestrator(GeminiProvider(Settings()))
    results = []
    service = ProductTruthService()
    for row in selected:
        product = service.create_from_raw_input(
            product_id=f"row-{row.row_number}",
            raw_values=row.raw_values,
            source=Source(
                source_id=f"input-{path.name}",
                source_type=SourceType.SUPPLIED_INPUT,
                authority=SourceAuthority.HIGH,
            ),
        )
        product, job = orchestrator.run(product, args.prompt_version)
        results.append(
            {
                "product_id": product.product_id,
                "state": job.state.value,
                "agent_runs": len(job.runs),
                "attributes": len(product.attributes),
            }
        )
    print(json.dumps({"status": "completed", "rows_selected": len(results), "results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(phase4_main())
