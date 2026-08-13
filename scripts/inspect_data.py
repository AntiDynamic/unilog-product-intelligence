"""Generate the machine-readable inventory for the real UniHack runtime files."""

import argparse
import json
import os
from pathlib import Path

from unilog_product_intelligence.data.inventory import EXPECTED_UNILOG_FILES, build_inventory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=os.getenv("UNILOG_DATA_DIR", "/mnt/data"))
    parser.add_argument(
        "--output", default="docs/research/data-inventory.json", help="Output JSON path"
    )
    args = parser.parse_args()
    inventory = build_inventory(args.data_root, EXPECTED_UNILOG_FILES)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(inventory.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Inventory written to {args.output}: {inventory.available_file_count} available, "
        f"{inventory.unavailable_file_count} unavailable"
    )


if __name__ == "__main__":
    main()
