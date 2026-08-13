from pathlib import Path

from openpyxl import Workbook

from unilog_product_intelligence.data.readers import read_tabular_file


def test_csv_reader_preserves_raw_values_and_normalized_values(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("field_a,brand\nvalue-a,-- Unbranded --\n", encoding="utf-8")

    result = read_tabular_file(source)

    assert result.source_file.sha256 is not None
    assert result.sheets[0].headers == ["field_a", "brand"]
    assert result.rows[0].raw_values["brand"] == "-- Unbranded --"
    assert result.rows[0].normalized_values["brand"] is None
    assert result.rows[0].normalization["brand"].reason == "placeholder"


def test_xlsx_reader_reports_sheet_and_merged_range(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Source"
    sheet.merge_cells("A1:B1")
    sheet["A1"] = "field_a"
    sheet["A2"] = "value-a"
    sheet["B2"] = "value-b"
    workbook.save(source)

    result = read_tabular_file(source)

    assert result.sheets[0].name == "Source"
    assert "A1:B1" in result.sheets[0].merged_ranges
    assert result.rows[0].raw_values["field_a"] == "value-a"
