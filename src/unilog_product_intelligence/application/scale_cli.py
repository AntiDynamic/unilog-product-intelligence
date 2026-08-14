"""CLI diagnostics and dry-run cost planning for Gemini scale operations."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path

from unilog_product_intelligence.application.optimization import cost_scenarios, group_manufacturers
from unilog_product_intelligence.application.scale import estimate_batch
from unilog_product_intelligence.config import Settings
from unilog_product_intelligence.data.readers import read_tabular_file


def cost_plan_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--task", default="product_understanding")
    parser.add_argument("--mode", default="auto")
    args = parser.parse_args()
    frame = read_tabular_file(Path(args.input))
    products = min(args.limit, len(frame.rows))
    rows = [dict(row.raw_values) for row in frame.rows[:products]]
    manufacturers = len(group_manufacturers(rows))
    plan = {
        "baseline": estimate_batch(products, manufacturers=manufacturers),
        "optimized": cost_scenarios(products, manufacturers=manufacturers),
    }
    print(json.dumps(plan, indent=2))


def diagnostics_main() -> None:
    settings = Settings()
    print(
        json.dumps(
            {
                "sdk_version": importlib.metadata.version("google-genai"),
                "model": settings.gemini_model,
                "live_external_execution": settings.live_external_execution,
                "gemini_key_configured": settings.gemini_api_key is not None,
                "provider_limits": {"rpm": "UNKNOWN", "input_tpm": "UNKNOWN", "rpd": "UNKNOWN"},
                "batch_support": "CONFIGURED_BY_SDK",
                "search_support": "CONFIGURED_BY_PROVIDER_TOOLS",
                "cache_support": "IMPLICIT_PROVIDER_BEHAVIOR",
            },
            indent=2,
        )
    )
