"""Bounded Phase 5 manufacturer-intelligence CLI."""

import argparse
import json
import os
from pathlib import Path

from unilog_product_intelligence.application.execution import GeminiExecutionService
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.config import Settings
from unilog_product_intelligence.data.readers import read_tabular_file
from unilog_product_intelligence.domain.truth import Source, SourceAuthority, SourceType
from unilog_product_intelligence.providers import GeminiProvider

from .core import (
    EvidenceExtractor,
    HtmlParser,
    ManufacturerProfile,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourceRecord,
    canonicalize_url,
)
from .service import ManufacturerIntelligenceService


def phase5_main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded manufacturer source intelligence")
    parser.add_argument("--input", default=os.getenv("UNILOG_INPUT_FILE"))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--row-id", type=int)
    parser.add_argument("--product-id")
    parser.add_argument("--manufacturer")
    parser.add_argument("--manufacturer-domain")
    parser.add_argument("--source-url")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.input:
        print(
            json.dumps(
                {"status": "input_unavailable", "reason": "pass --input or set UNILOG_INPUT_FILE"}
            )
        )
        return 2
    path = Path(args.input)
    if not path.is_file():
        print(json.dumps({"status": "input_unavailable", "path": str(path)}))
        return 2
    rows = read_tabular_file(path).rows
    selected = [row for row in rows if args.row_id is None or row.row_number == args.row_id]
    if args.product_id:
        selected = [row for row in selected if f"row-{row.row_number}" == args.product_id]
    if args.manufacturer:
        selected = [
            row
            for row in selected
            if str(row.raw_values.get("Part_Manuf") or "").casefold()
            == args.manufacturer.casefold()
        ]
    selected = selected[: max(0, args.limit)]
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "rows_selected": len(selected),
                    "source_url_supplied": bool(args.source_url),
                    "search_calls": 0,
                    "url_context_calls": 0,
                }
            )
        )
        return 0
    if not args.source_url or not args.manufacturer_domain:
        print(
            json.dumps(
                {
                    "status": "review_required",
                    "reason": (
                        "verified manufacturer domain and source URL are required; "
                        "discovery is candidate-only"
                    ),
                    "rows_selected": len(selected),
                }
            )
        )
        return 0
    source_url = canonicalize_url(args.source_url)
    provider = GeminiExecutionService(GeminiProvider(Settings()))
    service = ManufacturerIntelligenceService(
        SourceFetcher(), extractor=EvidenceExtractor(provider), parser=HtmlParser()
    )
    truth_service = ProductTruthService()
    results = []
    for row in selected:
        manufacturer = str(row.raw_values.get("Part_Manuf") or args.manufacturer or "")
        product = truth_service.create_from_raw_input(
            f"row-{row.row_number}",
            row.raw_values,
            Source(
                source_id=f"input-{path.name}",
                source_type=SourceType.SUPPLIED_INPUT,
                authority=SourceAuthority.HIGH,
            ),
        )
        source = SourceRecord(
            canonical_url=source_url,
            original_url=source_url,
            source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
            decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
            manufacturer_id=manufacturer,
            manufacturer_domain=args.manufacturer_domain,
            product_id=product.product_id,
        )
        product, job = service.process(
            product,
            source,
            ManufacturerProfile(
                manufacturer_id=manufacturer,
                canonical_name=manufacturer,
                verified_domains=(args.manufacturer_domain,),
            ),
            refresh=args.refresh,
        )
        results.append(
            {
                "product_id": product.product_id,
                "state": job.state.value,
                "cache_status": job.cache_status.value if job.cache_status else None,
                "evidence_count": job.evidence_count,
                "error": job.error,
            }
        )
    print(json.dumps({"status": "completed", "rows_selected": len(results), "results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(phase5_main())
