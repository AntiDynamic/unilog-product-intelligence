"""Command-line entry points for Phase 1 data operations."""

import argparse
import json
import os
from pathlib import Path

from .delivery import validate_delivery_csv
from .inventory import EXPECTED_UNILOG_FILES, build_inventory


def inspect_data_main() -> None:
    """Generate a JSON inventory for the configured runtime data directory."""

    parser = argparse.ArgumentParser(description="Generate the UniHack data inventory")
    parser.add_argument("--data-root", default=os.getenv("UNILOG_DATA_DIR", "/mnt/data"))
    parser.add_argument("--output", default="docs/research/data-inventory.json")
    args = parser.parse_args()
    inventory = build_inventory(args.data_root, EXPECTED_UNILOG_FILES)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(inventory.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Inventory written to {output}: {inventory.available_file_count} available, "
        f"{inventory.unavailable_file_count} unavailable"
    )


def validate_delivery_main() -> int:
    """Validate a delivery CSV against one JSON header contract."""

    parser = argparse.ArgumentParser(description="Validate a delivery CSV contract")
    parser.add_argument("delivery_csv")
    parser.add_argument("schema_json")
    args = parser.parse_args()
    schema = json.loads(Path(args.schema_json).read_text(encoding="utf-8"))
    result = validate_delivery_csv(args.delivery_csv, schema["headers"])
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0 if result.valid else 1
