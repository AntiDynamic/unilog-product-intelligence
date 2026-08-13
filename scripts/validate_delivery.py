"""Validate a delivery CSV against one authoritative JSON header contract."""

import argparse
import json
from pathlib import Path

from unilog_product_intelligence.data.delivery import validate_delivery_csv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("delivery_csv")
    parser.add_argument("schema_json")
    args = parser.parse_args()
    schema = json.loads(Path(args.schema_json).read_text(encoding="utf-8"))
    result = validate_delivery_csv(args.delivery_csv, schema["headers"])
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
