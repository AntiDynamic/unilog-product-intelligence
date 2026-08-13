from pathlib import Path

from unilog_product_intelligence.data.delivery import validate_delivery_csv


def test_delivery_validation_accepts_exact_header_order_and_width(tmp_path: Path) -> None:
    source = tmp_path / "delivery.csv"
    source.write_text("first,second\na,b\n", encoding="utf-8")

    result = validate_delivery_csv(source, ["first", "second"])

    assert result.valid is True
    assert result.invalid_row_widths == {}


def test_delivery_validation_reports_missing_extra_order_and_width(tmp_path: Path) -> None:
    source = tmp_path / "delivery.csv"
    source.write_text("second,unexpected\na\n", encoding="utf-8")

    result = validate_delivery_csv(source, ["first", "second"])

    assert result.valid is False
    assert result.missing_headers == ["first"]
    assert result.unexpected_headers == ["unexpected"]
    assert result.order_changed is True
    assert result.invalid_row_widths == {2: 1}
