"""Bounded Phase 4 real-input execution and single-row inspection paths."""

import argparse
import json
import os
from pathlib import Path

from unilog_product_intelligence.application.execution import GeminiExecutionService
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.config import Settings
from unilog_product_intelligence.data.contracts import DatasetRow
from unilog_product_intelligence.data.readers import read_tabular_file
from unilog_product_intelligence.domain.truth import Source, SourceAuthority, SourceType
from unilog_product_intelligence.providers import GeminiProvider

from .inspection import ProductInspectionResult, build_inspection, render_inspection_markdown
from .orchestration import ProductOrchestrator


def phase4_main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded Gemini orchestration over real UniLog rows"
    )
    parser.add_argument("--input", default=os.getenv("UNILOG_INPUT_FILE"))
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--row-id", type=_parse_row_id)
    parser.add_argument("--prompt-version", default="v1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--inspect", action="store_true", help="Emit full structured inspection for exactly one row"
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable inspection JSON")
    parser.add_argument("--output", help="Optional JSON inspection output path")
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
    if args.inspect:
        if len(selected) != 1:
            print(
                json.dumps(
                    {"status": "inspection_requires_one_row", "rows_selected": len(selected)}
                )
            )
            return 2
        inspection = _run_inspection(path, selected[0], args.prompt_version)
        return _emit_inspection(inspection, args.output, args.json)
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
    orchestrator = ProductOrchestrator(GeminiExecutionService(GeminiProvider(Settings())))
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
                "runs": [
                    {
                        "task": run.task,
                        "status": run.status,
                        "request_id": run.request_id,
                        "latency_ms": run.latency_ms,
                        "error": run.error,
                    }
                    for run in job.runs
                ],
            }
        )
    print(json.dumps({"status": "completed", "rows_selected": len(results), "results": results}))
    return 0


def _run_inspection(path: Path, row: DatasetRow, prompt_version: str) -> ProductInspectionResult:
    """Execute one selected row through the existing three-agent path."""

    tabular = read_tabular_file(path)
    source = Source(
        source_id=f"input-{path.name}",
        source_type=SourceType.SUPPLIED_INPUT,
        authority=SourceAuthority.HIGH,
    )
    raw_values = row.raw_values
    row_number = row.row_number
    product = ProductTruthService().create_from_raw_input(
        product_id=f"row-{row_number}", raw_values=raw_values, source=source
    )
    orchestrator = ProductOrchestrator(GeminiExecutionService(GeminiProvider(Settings())))
    product, job = orchestrator.run(product, prompt_version)
    return build_inspection(product, job, input_filename=str(tabular.source_file.path))


def _emit_inspection(
    inspection: ProductInspectionResult, output: str | None, machine_json: bool
) -> int:
    payload = inspection.model_dump(mode="json")
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    report_dir = Path("docs/research")
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = (
        "row-2-live-inspection"
        if inspection.product_id == "row-2"
        else f"{inspection.product_id}-inspection"
    )
    (report_dir / f"{stem}.json").write_text(text + "\n", encoding="utf-8")
    (report_dir / f"{stem}.md").write_text(render_inspection_markdown(inspection), encoding="utf-8")
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
    if machine_json:
        print(text)
    else:
        print(render_inspection_markdown(inspection))
    return 0


def _parse_row_id(value: str) -> int:
    """Accept the existing numeric row id and the documented row-2 form."""
    text = value.removeprefix("row-")
    try:
        row_id = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("row id must be an integer or row-N") from error
    if row_id < 1:
        raise argparse.ArgumentTypeError("row id must be positive")
    return row_id


if __name__ == "__main__":
    raise SystemExit(phase4_main())
