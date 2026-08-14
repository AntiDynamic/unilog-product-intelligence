"""Real-input deterministic preprocessing diagnostics without copying product rows."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from unilog_product_intelligence.data.normalize import normalize_value

from .normalization import normalize_part_number


def inspect_input(path: str | Path) -> dict[str, Any]:
    """Compute aggregate diagnostics from the actual supplied input CSV."""

    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    placeholder_counts: Counter[str] = Counter()
    normalized_mpn_counts: Counter[str] = Counter()
    normalization_opportunities = 0
    for row in rows:
        for name, value in row.items():
            normalized = normalize_value(value)
            if normalized.reason == "placeholder":
                placeholder_counts[name] += 1
        part_number = normalize_part_number(row.get("Mfg_Part_Num"))
        if part_number.normalized_value:
            normalized_mpn_counts[part_number.normalized_value] += 1
            if part_number.reason is not None:
                normalization_opportunities += 1
    exact_duplicate_groups = sum(1 for count in normalized_mpn_counts.values() if count > 1)
    potential_duplicate_rows = sum(count for count in normalized_mpn_counts.values() if count > 1)
    return {
        "source_file": str(source),
        "sha256": _sha256(source),
        "total_rows": len(rows),
        "headers": list(rows[0].keys()) if rows else [],
        "placeholder_counts": dict(sorted(placeholder_counts.items())),
        "normalization_opportunities": normalization_opportunities,
        "exact_normalized_mpn_duplicate_groups": exact_duplicate_groups,
        "rows_in_exact_normalized_mpn_duplicate_groups": potential_duplicate_rows,
        "reference_data_availability": {
            "manufacturer": "unavailable",
            "brand": "unavailable",
            "taxonomy": "unavailable",
            "lov": "unavailable",
            "uom": "unavailable",
            "fraction": "unavailable",
            "rules": "unavailable",
        },
        "notes": [
            "No reference resolution was claimed because official manufacturer, brand, taxonomy, "
            "LOV, UOM, fraction, and rule files are unavailable.",
            "Duplicate signals are exact normalized MPN groups only; they are review signals, "
            "not product merges.",
        ],
    }


def write_diagnostic(input_path: str | Path, output_path: str | Path) -> None:
    report = inspect_input(input_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
