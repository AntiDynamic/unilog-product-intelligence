from pathlib import Path

from unilog_product_intelligence.data.inventory import build_inventory


def test_inventory_metrics_are_generated_from_source_file(tmp_path: Path) -> None:
    source = tmp_path / "metadata.csv"
    source.write_text(
        "field_a,brand\nvalue-a,-- Unbranded --\nvalue-a,-- Unbranded --\n", encoding="utf-8"
    )

    inventory = build_inventory(tmp_path, [source.name])
    report = inventory.files[0]

    assert report.row_count == 2
    assert report.column_count == 2
    assert report.duplicate_row_count == 1
    assert report.placeholder_counts["brand"] == 2
    assert report.null_counts["brand"] == 0
