"""Authoritative official delivery-schema extraction and validation."""

import csv
import json
from collections import Counter
from pathlib import Path

from .contracts import ValidationResult


def extract_delivery_schema(path: str | Path) -> list[str]:
    """Extract the exact first CSV row without renaming or reordering headers."""

    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle), [])


def save_delivery_schema(path: str | Path, output: str | Path) -> None:
    """Persist the exact observed header contract as machine-readable JSON."""

    headers = extract_delivery_schema(path)
    payload = {
        "source_file": str(path),
        "header_count": len(headers),
        "headers": headers,
    }
    Path(output).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def validate_delivery_csv(
    delivery_path: str | Path, expected_headers: list[str]
) -> ValidationResult:
    """Detect contract/header/row-width violations deterministically."""

    with Path(delivery_path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    observed = rows[0] if rows else []
    expected_set = set(expected_headers)
    observed_set = set(observed)
    duplicates = sorted(header for header, count in Counter(observed).items() if count > 1)
    invalid_widths = {
        row_number: len(row)
        for row_number, row in enumerate(rows[1:], start=2)
        if len(row) != len(expected_headers)
    }
    missing = [header for header in expected_headers if header not in observed_set]
    unexpected = [header for header in observed if header not in expected_set]
    order_changed = observed != expected_headers
    valid = (
        not missing
        and not unexpected
        and not duplicates
        and not order_changed
        and not invalid_widths
    )
    return ValidationResult(
        valid=valid,
        expected_headers=expected_headers,
        observed_headers=observed,
        missing_headers=missing,
        unexpected_headers=unexpected,
        duplicate_headers=duplicates,
        order_changed=order_changed,
        invalid_row_widths=invalid_widths,
    )
