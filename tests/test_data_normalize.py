from unilog_product_intelligence.data.normalize import normalize_value


def test_official_placeholder_preserves_raw_value_and_normalizes_to_null() -> None:
    result = normalize_value("-- No Unilog Brand --")

    assert result.raw_value == "-- No Unilog Brand --"
    assert result.normalized_value is None
    assert result.reason == "placeholder"


def test_blank_and_regular_values_have_explicit_reasons() -> None:
    assert normalize_value("   ").reason == "blank"
    assert normalize_value("  Valve  ").model_dump() == {
        "raw_value": "  Valve  ",
        "normalized_value": "Valve",
        "reason": "trimmed",
    }
