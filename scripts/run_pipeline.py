# ruff: noqa: E402 E501
"""End-to-end UNILOG pipeline runner: Input CSV -> Delivery CSV.

Supports two explicit execution modes:
  1. LIVE_DETERMINISTIC (--mode live-deterministic, default):
     - Uses DeterministicEvaluationProvider (zero Gemini cost/API calls).
     - Live HTTP retrieval enabled for verified manufacturer domains.
     - Deterministic rule-based Phase 4 extraction & Phase 6 enrichment.
     - Fast, reproducible regression benchmark for retrieval and taxonomy.

  2. LIVE_GEMINI (--mode live-gemini):
     - Uses real GeminiProvider (requires GEMINI_API_KEY).
     - Live Gemini orchestration for Phase 4 understanding & Phase 6 enrichment.
     - Live HTTP retrieval and targeted Gemini search for Phase 5 discovery.
     - Captures real model names, token counts, request IDs, and latencies.
     - Fails closed immediately if GEMINI_API_KEY is not configured (no silent fallback).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── Resolve project root so imports work whether run from root or scripts/ ─────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from unilog_product_intelligence.agents.orchestration import ProductOrchestrator  # noqa: E402
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
from unilog_product_intelligence.providers.factory import (  # noqa: E402
    ExecutionMode,
    GeminiConfigurationError,
    build_provider,
)
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
        "--mode",
        choices=["live-deterministic", "live-gemini", "deterministic", "gemini"],
        default="live-deterministic",
        help=(
            "Pipeline execution mode:\n"
            "  live-deterministic (default): DeterministicEvaluationProvider with live HTTP retrieval "
            "(zero Gemini cost/calls; measures deterministic retrieval & normalization)\n"
            "  live-gemini: Real GeminiProvider with live HTTP retrieval and real AI enrichment "
            "(requires GEMINI_API_KEY; measures real end-to-end AI product intelligence)"
        ),
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
        help="Skip live HTTP retrieval (use provider-only without live network fetching)",
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

    # ── Resolve execution mode and provider (Fail-Closed on missing config) ───
    exec_mode = ExecutionMode.from_str(args.mode)
    try:
        provider = build_provider(exec_mode)
    except GeminiConfigurationError as err:
        print(f"\nERROR: {err}\n", file=sys.stderr)
        print("To run in LIVE_GEMINI mode, ensure GEMINI_API_KEY is set in your environment or .env file.", file=sys.stderr)
        print("Alternatively, use `--mode live-deterministic` for zero-cost deterministic execution.", file=sys.stderr)
        sys.exit(1)

    provider_name = type(provider).__name__
    provider_model = getattr(provider, "model", "deterministic-evaluator")

    print("=" * 65)
    print("UNILOG PRODUCT INTELLIGENCE PIPELINE")
    print("=" * 65)
    print(f"Execution Mode: {exec_mode.value}")
    print(f"Provider:       {provider_name}")
    print(f"Model:          {provider_model}")
    print(f"Live Network:   {not args.no_live}")
    print(f"Input:          {input_path}")
    print(f"Output:         {output_path}")
    print("=" * 65)

    # ── Load schema and configure adapter ────────────────────────────────────
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)
    headers = list(contract.headers)
    print(f"Loaded delivery schema: {len(headers)} columns")

    # ── Load input rows ───────────────────────────────────────────────────────
    read_result = read_tabular_file(input_path)
    rows = read_result.rows
    if args.limit:
        rows = rows[: args.limit]
    total = len(rows)
    print(f"Processing {total} rows" + (f" (limit={args.limit})" if args.limit else ""))

    # ── Wire pipeline ─────────────────────────────────────────────────────────
    truth_service = ProductTruthService()
    fetcher = SourceFetcher(timeout=args.timeout or 3.5, max_retries=0, requests_per_second=5.0)
    source_disc = ProductSourceDiscoveryService(fetcher=fetcher)
    pipeline = _build_pipeline(
        provider, truth_service, fetcher, source_disc, live=not args.no_live
    )

    # ── Open output CSV for incremental writing ───────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats = {"enriched": 0, "review_required": 0, "blocked": 0, "error": 0}
    traces: list[dict[str, Any]] = []

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

                # Phase 4 Telemetry
                p4_runs = result.phase4_job.runs if result.phase4_job else []
                p4_model = p4_runs[0].model if p4_runs and p4_runs[0].model else (provider_model if p4_runs else None)
                p4_calls = len(p4_runs)
                p4_input_tokens = sum(r.input_tokens for r in p4_runs if r.input_tokens is not None) if any(r.input_tokens is not None for r in p4_runs) else None
                p4_output_tokens = sum(r.output_tokens for r in p4_runs if r.output_tokens is not None) if any(r.output_tokens is not None for r in p4_runs) else None
                p4_cached_tokens = sum(r.cached_tokens for r in p4_runs if r.cached_tokens is not None) if any(r.cached_tokens is not None for r in p4_runs) else None
                p4_total_tokens = sum(r.total_tokens for r in p4_runs if r.total_tokens is not None) if any(r.total_tokens is not None for r in p4_runs) else None
                p4_latency_ms = sum(r.latency_ms for r in p4_runs if r.latency_ms is not None) if any(r.latency_ms is not None for r in p4_runs) else None
                p4_request_ids = [r.request_id for r in p4_runs if r.request_id]
                p4_error = next((r.error for r in p4_runs if r.error), None)
                p4_status = "FAILED" if result.phase4_job and result.phase4_job.state.value == "failed" else "COMPLETED"

                # Phase 5 Telemetry
                disc = result.discovery
                p5_search_requested = bool(disc and disc.search_requested)
                p5_search_tool_calls = disc.search_tool_calls if disc else 0
                p5_search_calls = 1 if (disc and disc.search_tool_calls > 0) else 0
                p5_search_result_count = disc.search_result_count if disc else 0
                p5_search_result_urls = list(disc.search_result_urls) if disc else []
                p5_model = disc.model if disc else None
                p5_input_tokens = disc.input_tokens if disc else None
                p5_output_tokens = disc.output_tokens if disc else None
                p5_cached_tokens = disc.cached_tokens if disc else None
                p5_latency_ms = disc.latency_ms if disc else None
                p5_request_id = disc.request_id if disc else None
                p5_failure_reason = (
                    result.blocker
                    or (result.manufacturer_job.failure_reason.value if result.manufacturer_job and result.manufacturer_job.failure_reason else None)
                    or (disc.failure_reason.value if disc and disc.failure_reason else None)
                )

                # Phase 6 Telemetry
                enrich = result.enrichment
                p6_calls = enrich.metrics.agent_calls if enrich else 0
                p6_input_tokens = enrich.metrics.input_tokens if (enrich and enrich.metrics.input_tokens > 0) else None
                p6_output_tokens = enrich.metrics.output_tokens if (enrich and enrich.metrics.output_tokens > 0) else None
                p6_cached_tokens = enrich.metrics.cached_tokens if (enrich and enrich.metrics.cached_tokens > 0) else None
                p6_latency_ms = None
                p6_error = enrich.error if enrich else None
                p6_status = enrich.status.value if enrich else "UNKNOWN"
                p6_publication_state = enrich.publication_state.value if enrich else "REVIEW_REQUIRED"

                p6_candidates = enrich.candidates if enrich else ()
                p6_planned = len(enrich.attribute_plans) if enrich else 0
                p6_proposed = len(p6_candidates)
                p6_validated = sum(
                    1
                    for c in p6_candidates
                    if getattr(c, "status", None) in {"VERIFIED", "ENRICHED", "NORMALIZED"}
                    or getattr(getattr(c, "status", None), "value", None) in {"VERIFIED", "ENRICHED", "NORMALIZED"}
                    or getattr(c, "validation_state", "") in {"VALID", "PASSED"}
                )
                p6_review = sum(
                    1
                    for c in p6_candidates
                    if getattr(c, "status", None) == "REVIEW_REQUIRED"
                    or getattr(getattr(c, "status", None), "value", None) == "REVIEW_REQUIRED"
                    or getattr(c, "validation_state", "") == "REVIEW_REQUIRED"
                )
                p6_rejected = sum(
                    1
                    for c in p6_candidates
                    if getattr(c, "status", None) == "REJECTED"
                    or getattr(getattr(c, "status", None), "value", None) == "REJECTED"
                    or getattr(c, "validation_state", "") == "REJECTED"
                )

                traces.append(
                    {
                        "row_number": row_num,
                        "product_id": f"row-{row_num}",
                        "input_mpn": mpn,
                        "input_manufacturer": manuf,
                        "input_brand_fields": {
                            "Unilog_Brand": str(row.raw_values.get("Unilog_Brand") or ""),
                            "E1_Brand": str(row.raw_values.get("E1_Brand") or ""),
                            "DIB_Brand": str(row.raw_values.get("DIB_Brand") or ""),
                        },
                        "resolved_manufacturer": (
                            str(result.product_truth.identity.manufacturer.normalized_value or "")
                            if getattr(result.product_truth.identity, "manufacturer", None)
                            else ""
                        ),
                        "resolved_brand": (
                            str(result.product_truth.identity.brand.normalized_value or "")
                            if getattr(result.product_truth.identity, "brand", None)
                            else ""
                        ),
                        "execution_mode": exec_mode.value,
                        "duration_ms": duration,
                        "phase4": {
                            "status": p4_status,
                            "provider_model": p4_model,
                            "provider_calls": p4_calls,
                            "input_tokens": p4_input_tokens,
                            "output_tokens": p4_output_tokens,
                            "cached_tokens": p4_cached_tokens,
                            "total_tokens": p4_total_tokens,
                            "latency_ms": p4_latency_ms,
                            "request_ids": p4_request_ids,
                            "error": p4_error,
                        },
                        "phase5": {
                            "domain_candidates": [
                                {
                                    "domain": c.domain,
                                    "status": c.status.value,
                                    "source": c.source,
                                    "reason": c.reason,
                                }
                                for c in (result.discovery.candidates if result.discovery else ())
                            ],
                            "verified_domains": [
                                c.domain
                                for c in (result.discovery.candidates if result.discovery else ())
                                if c.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
                            ],
                            "retrieval_strategies_attempted": list(
                                result.discovery.retrieval_strategies_attempted
                                if result.discovery
                                else ()
                            ),
                            "candidate_urls": list(
                                result.discovery.search_result_urls if result.discovery else ()
                            ),
                            "fetched_urls": [
                                s.uri for s in result.product_truth.sources if s.uri
                            ],
                            "source_decision": (
                                result.manufacturer_job.state.value
                                if result.manufacturer_job
                                else "none"
                            ),
                            "source_status": (
                                "success"
                                if any(
                                    s.authority in {SourceAuthority.HIGH, SourceAuthority.AUTHORITATIVE}
                                    for s in result.product_truth.sources
                                )
                                else "not_found"
                            ),
                            "identity_score": (
                                1.0
                                if any(
                                    s.authority in {SourceAuthority.HIGH, SourceAuthority.AUTHORITATIVE}
                                    for s in result.product_truth.sources
                                )
                                else 0.0
                            ),
                            "identity_classification": (
                                "STRONG_MATCH"
                                if any(
                                    s.authority in {SourceAuthority.HIGH, SourceAuthority.AUTHORITATIVE}
                                    for s in result.product_truth.sources
                                )
                                else None
                            ),
                            "evidence_count": len(result.product_truth.evidence),
                            "search_requested": p5_search_requested,
                            "search_tool_calls": p5_search_tool_calls,
                            "search_calls": p5_search_calls,
                            "search_result_count": p5_search_result_count,
                            "search_result_urls": p5_search_result_urls,
                            "model": p5_model,
                            "input_tokens": p5_input_tokens,
                            "output_tokens": p5_output_tokens,
                            "cached_tokens": p5_cached_tokens,
                            "latency_ms": p5_latency_ms,
                            "request_id": p5_request_id,
                            "failure_reason": p5_failure_reason,
                        },
                        "phase6": {
                            "status": p6_status,
                            "publication_state": p6_publication_state,
                            "enrichment_model": provider_model if p6_calls > 0 else None,
                            "enrichment_calls": p6_calls,
                            "attributes_planned": p6_planned,
                            "attributes_candidate": p6_proposed,
                            "attributes_validated": p6_validated,
                            "attributes_review": p6_review,
                            "attributes_rejected": p6_rejected,
                            "input_tokens": p6_input_tokens,
                            "output_tokens": p6_output_tokens,
                            "cached_tokens": p6_cached_tokens,
                            "latency_ms": p6_latency_ms,
                            "error": p6_error,
                        },
                        "delivery": {
                            "non_empty_fields": sum(
                                1 for v in delivery.as_row() if v is not None and str(v).strip()
                            ),
                            "total_fields": len(headers),
                            "completeness_pct": round(
                                sum(1 for v in delivery.as_row() if v is not None and str(v).strip())
                                / len(headers)
                                * 100,
                                2,
                            ),
                        },
                        "final_status": result.status.value,
                        "publication_state": p6_publication_state,
                        "blocker": result.blocker,
                        "failure_reason": p5_failure_reason,
                    }
                )

            except Exception as err:
                # Write empty row to preserve row alignment
                writer.writerow([None] * len(headers))
                out_file.flush()
                stats["error"] += 1
                duration = int((time.perf_counter() - t0) * 1000)
                print(f"ERROR: {type(err).__name__}: {err} ({duration}ms)")

    # ── Write traces JSON ─────────────────────────────────────────────────────
    traces_path = output_path.with_name(f"{output_path.stem}_traces.json")
    with traces_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "execution_mode": exec_mode.value,
                "provider": provider_name,
                "model": provider_model,
                "live_http_retrieval": not args.no_live,
                "timestamp": datetime.now(UTC).isoformat(),
                "total_rows": total,
                "stats": stats,
                "traces": traces,
            },
            f,
            indent=2,
        )
    print(f"Traces: {traces_path}")

    # ── Print summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("PIPELINE COMPLETE")
    print(f"Output: {output_path}")
    print(f"Mode:   {exec_mode.value}")
    print(f"Rows:   {total}")
    print(f"  ENRICHED:        {stats.get('enriched', 0):4d}")
    print(f"  REVIEW_REQUIRED: {stats.get('review_required', 0):4d}")
    print(f"  BLOCKED:         {stats.get('blocked', 0):4d}")
    print(f"  ERRORS:          {stats.get('error', 0):4d}")
    print("=" * 65)


if __name__ == "__main__":
    main()
