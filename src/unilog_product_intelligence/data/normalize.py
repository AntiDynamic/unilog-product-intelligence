"""Deterministic source-value normalization with provenance."""

from collections.abc import Mapping
from typing import Any

from .contracts import NormalizedValue

PLACEHOLDER_VALUES = frozenset(
    {
        "-- Unbranded --",
        "-- No Unilog Brand --",
        "-- No DIB Brand --",
    }
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def normalize_value(value: Any) -> NormalizedValue:
    """Normalize known placeholders and blank values without losing the raw value."""

    text = _text(value)
    if text is None:
        return NormalizedValue(raw_value=value, normalized_value=None, reason="null")

    stripped = text.strip()
    if stripped == "":
        return NormalizedValue(raw_value=value, normalized_value=None, reason="blank")
    if stripped in PLACEHOLDER_VALUES:
        return NormalizedValue(raw_value=value, normalized_value=None, reason="placeholder")
    reason = "trimmed" if stripped != text else None
    return NormalizedValue(raw_value=value, normalized_value=stripped, reason=reason)


def normalize_row(values: Mapping[str, Any]) -> dict[str, NormalizedValue]:
    """Normalize each field in a row independently."""

    return {name: normalize_value(value) for name, value in values.items()}
