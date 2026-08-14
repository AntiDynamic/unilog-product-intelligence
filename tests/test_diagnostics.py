import json
from pathlib import Path

from unilog_product_intelligence.deterministic.diagnostics import inspect_input, write_diagnostic


def test_diagnostic_reports_aggregates_without_product_rows(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    source.write_text(
        "Mfg_Part_Num,Unilog_Brand\n"
        " sample-part ,-- No Unilog Brand --\n"
        "sample-part,Synthetic Brand\n",
        encoding="utf-8",
    )

    report = inspect_input(source)
    output = tmp_path / "diagnostic.json"
    write_diagnostic(source, output)

    assert report["total_rows"] == 2
    assert report["exact_normalized_mpn_duplicate_groups"] == 1
    assert report["placeholder_counts"] == {"Unilog_Brand": 1}
    assert "rows" not in report
    assert json.loads(output.read_text(encoding="utf-8"))["sha256"] == report["sha256"]
