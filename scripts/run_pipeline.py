# ruff: noqa: E402 E501
"""End-to-end UNILOG pipeline runner: Input CSV -> Delivery CSV.

Usage
-----
    python scripts/run_pipeline.py \
        --input "Unihack_ Sample Dataset - Input.csv" \
        --output delivery_output.csv \
        [--limit 50] \
        [--timeout 10] \
        [--schema docs/research/delivery-schema.json]

The script reads each input row, runs it through the full Phase65Pipeline
(Phase 4 -> Phase 5 -> Phase 6), maps the result to the UniHack 252-column
delivery format, and writes the output CSV incrementally (one row at a time,
flushed after each write).

No values are fabricated.  Columns that cannot be derived are left empty.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

# ── Resolve project root so imports work whether run from root or scripts/ ─────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from unilog_product_intelligence.agents.orchestration import ProductOrchestrator  # noqa: E402
from unilog_product_intelligence.application.evaluation import (
    DeterministicEvaluationProvider,  # noqa: E402
)
from unilog_product_intelligence.application.phase65 import Phase65Pipeline  # noqa: E402
from unilog_product_intelligence.application.product_truth import ProductTruthService  # noqa: E402
from unilog_product_intelligence.data.readers import read_tabular_file  # noqa: E402
from unilog_product_intelligence.delivery.adapter import (  # noqa: E402
    DeliverySchemaContract,
    Phase65ResultDeliveryAdapter,
)
from unilog_product_intelligence.domain.truth import (  # noqa: E402
    Source,
    SourceAuthority,
    SourceType,
)
from unilog_product_intelligence.enrichment.agent import (
    EvidenceGroundedEnrichmentAgent,  # noqa: E402
)
from unilog_product_intelligence.enrichment.planner import AttributePlanner  # noqa: E402
from unilog_product_intelligence.enrichment.service import EnrichmentService  # noqa: E402
from unilog_product_intelligence.enrichment.validation import ValidationPipeline  # noqa: E402
from unilog_product_intelligence.retrieval.agents import (  # noqa: E402
    DiscoveryResult,
    ManufacturerDiscoveryAgent,
)
from unilog_product_intelligence.retrieval.core import (  # noqa: E402
    DomainResolver,
    EvidenceExtractor,
    ManufacturerProfile,
    SourceDecision,
    SourceFetcher,
    SourcePolicy,
    SourceRecord,
    SourceVerifier,
    _host,
)
from unilog_product_intelligence.retrieval.service import (
    ManufacturerIntelligenceService,  # noqa: E402
)
from unilog_product_intelligence.retrieval.source_discovery import (  # noqa: E402
    ProductSourceDiscoveryService,
)

# ── Default paths relative to project root ────────────────────────────────────
_DEFAULT_INPUT = _ROOT / "Unihack_ Sample Dataset - Input.csv"
_DEFAULT_OUTPUT = _ROOT / "delivery_output.csv"
_DEFAULT_SCHEMA = _ROOT / "docs" / "research" / "delivery-schema.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="UNILOG Pipeline: Input CSV -> 252-column Delivery CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        default=str(_DEFAULT_INPUT),
        help="Path to input CSV (default: Unihack_ Sample Dataset - Input.csv)",
    )
    parser.add_argument(
        "--output",
        default=str(_DEFAULT_OUTPUT),
        help="Path to output delivery CSV (default: delivery_output.csv)",
    )
    parser.add_argument(
        "--schema",
        default=str(_DEFAULT_SCHEMA),
        help="Path to delivery-schema.json (default: docs/research/delivery-schema.json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N rows (default: all rows)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.5,
        help="HTTP timeout per request in seconds (default: 3.5)",
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        help="Skip live HTTP retrieval (use deterministic provider only; faster, less complete)",
    )
    return parser.parse_args()


def _build_pipeline(
    provider: object,
    truth_service: ProductTruthService,
    fetcher: SourceFetcher,
    source_disc: ProductSourceDiscoveryService,
    *,
    live: bool = True,
) -> Phase65Pipeline:
    """Wire all services into a Phase65Pipeline with a working source_binding."""

    resolver = DomainResolver()
    disc_agent = ManufacturerDiscoveryAgent(provider=provider, resolver=resolver)  # type: ignore[arg-type]
    extractor = EvidenceExtractor(provider=provider)  # type: ignore[arg-type]
    mfg_service = ManufacturerIntelligenceService(fetcher=fetcher, extractor=extractor)
    enrichment_service = EnrichmentService(
        planner=AttributePlanner(),
        agent=EvidenceGroundedEnrichmentAgent(provider=provider),  # type: ignore[arg-type]
        validator=ValidationPipeline(),
        truth_service=truth_service,
    )

    def source_binding(
        product: object, disc: DiscoveryResult
    ) -> tuple[SourceRecord, ManufacturerProfile] | None:
        """Discover and select the best matching product source."""
        from unilog_product_intelligence.domain.truth import ProductTruth  # local import

        assert isinstance(product, ProductTruth)
        mfg_name = str(
            getattr(getattr(product.identity, "manufacturer", None), "normalized_value", None)
            or getattr(getattr(product.identity, "manufacturer", None), "raw_value", None)
            or product.raw_value("Part_Manuf")
            or ""
        )
        # Separate verified candidates vs unverified candidate domains
        verified_candidates = tuple(
            c
            for c in disc.candidates
            if c.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
        )
        candidate_candidates = tuple(
            c
            for c in disc.candidates
            if c.status == SourceDecision.CANDIDATE_MANUFACTURER_SOURCE
        )
        if not verified_candidates:
            # If no verified domain exists, do NOT create a profile that falsely claims candidate domains are verified.
            return None

        profile = ManufacturerProfile(
            manufacturer_id=mfg_name or "unknown",
            canonical_name=mfg_name or "unknown",
            verified_domains=tuple(c.domain for c in verified_candidates),
            candidate_domains=tuple(c.domain for c in candidate_candidates),
        )
        candidates = source_disc.discover(
            product, profile, candidate_urls=disc.search_result_urls
        )
        if not candidates:
            return None
        best = candidates[0]
        best_domain = _host(best.url)

        # Ensure the discovered candidate is verified against the profile
        candidate_source = SourceRecord(
            canonical_url=best.url,
            original_url=best.url,
            source_kind=best.source_kind,
            decision=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
            manufacturer_id=profile.manufacturer_id,
            manufacturer_domain=best_domain,
            product_id=product.product_id,
        )
        verified_source = SourceVerifier(SourcePolicy()).verify_source(candidate_source, profile)
        if verified_source.decision != SourceDecision.VERIFIED_MANUFACTURER_SOURCE:
            return None

        return verified_source, profile

    return Phase65Pipeline(
        orchestrator=ProductOrchestrator(provider, truth_service),  # type: ignore[arg-type]
        discovery=disc_agent,
        manufacturer=mfg_service,
        enrichment=enrichment_service,
        source_binding=source_binding if live else None,
    )


def main() -> None:
    args = _parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    schema_path = Path(args.schema)

    # ── Validate inputs ───────────────────────────────────────────────────────
    if not input_path.is_file():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    if not schema_path.is_file():
        print(f"ERROR: Schema file not found: {schema_path}", file=sys.stderr)
        print("       Run: python -m unilog_product_intelligence.data.cli save-schema",
              file=sys.stderr)
        sys.exit(1)

    # ── Load schema and configure adapter ────────────────────────────────────
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)
    headers = list(contract.headers)
    print(f"Loaded delivery schema: {len(headers)} columns")

    # ── Load input rows ───────────────────────────────────────────────────────
    print(f"Reading input: {input_path}")
    read_result = read_tabular_file(input_path)
    rows = read_result.rows
    if args.limit:
        rows = rows[: args.limit]
    total = len(rows)
    print(f"Processing {total} rows" + (f" (limit={args.limit})" if args.limit else ""))

    # ── Wire pipeline ─────────────────────────────────────────────────────────
    truth_service = ProductTruthService()
    provider = DeterministicEvaluationProvider()
    fetcher = SourceFetcher(timeout=args.timeout or 3.5, max_retries=0, requests_per_second=5.0)
    source_disc = ProductSourceDiscoveryService(fetcher=fetcher)
    pipeline = _build_pipeline(
        provider, truth_service, fetcher, source_disc, live=not args.no_live
    )

    # ── Open output CSV for incremental writing ───────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats = {"enriched": 0, "review_required": 0, "blocked": 0, "error": 0}

    with output_path.open("w", newline="", encoding="utf-8-sig") as out_file:
        writer = csv.writer(out_file, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        out_file.flush()

        for idx, row in enumerate(rows, start=1):
            row_num = row.row_number
            mpn = str(row.raw_values.get("Mfg_Part_Num") or "")
            manuf = str(row.raw_values.get("Part_Manuf") or "")
            label = f"[{idx:4d}/{total}] Row {row_num:4d} | MPN={mpn[:30]:<30} | Manuf={manuf[:28]:<28}"
            print(label, end=" | ", flush=True)
            t0 = time.perf_counter()
            try:
                # Build ProductTruth from raw row
                source = Source(
                    source_id=f"input-row-{row_num}",
                    source_type=SourceType.SUPPLIED_INPUT,
                    authority=SourceAuthority.HIGH,
                )
                product = truth_service.create_from_raw_input(
                    f"row-{row_num}", row.raw_values, source
                )

                # Run pipeline
                result = pipeline.run(product)

                # Map to delivery record
                delivery = adapter.to_record(result)
                writer.writerow(delivery.as_row())
                out_file.flush()

                status = result.status.value
                stats[status.lower().replace(" ", "_")] = stats.get(
                    status.lower().replace(" ", "_"), 0
                ) + 1
                duration = int((time.perf_counter() - t0) * 1000)
                blocker = f" [{result.blocker}]" if result.blocker else ""
                print(f"{status}{blocker} ({duration}ms)")

            except Exception as err:
                # Write empty row to preserve row alignment
                writer.writerow([None] * len(headers))
                out_file.flush()
                stats["error"] += 1
                duration = int((time.perf_counter() - t0) * 1000)
                print(f"ERROR: {type(err).__name__}: {err} ({duration}ms)")

    # ── Print summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print(f"Output: {output_path}")
    print(f"Rows:   {total}")
    print(f"  ENRICHED:        {stats.get('enriched', 0):4d}")
    print(f"  REVIEW_REQUIRED: {stats.get('review_required', 0):4d}")
    print(f"  BLOCKED:         {stats.get('blocked', 0):4d}")
    print(f"  ERRORS:          {stats.get('error', 0):4d}")
    print("=" * 60)


if __name__ == "__main__":
    main()
