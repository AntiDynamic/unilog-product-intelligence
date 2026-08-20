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
import concurrent.futures
import csv
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── Resolve project root so imports work whether run from root or scripts/ ─────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from unilog_product_intelligence.agents.orchestration import ProductOrchestrator  # noqa: E402
from unilog_product_intelligence.application.phase65 import (  # noqa: E402
    Phase65Pipeline,
    Phase65Result,
)
from unilog_product_intelligence.application.product_truth import ProductTruthService  # noqa: E402
from unilog_product_intelligence.config import get_settings  # noqa: E402
from unilog_product_intelligence.data.readers import read_tabular_file  # noqa: E402
from unilog_product_intelligence.delivery.adapter import (  # noqa: E402
    DeliverySchemaContract,
    Phase65ResultDeliveryAdapter,
)
from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket  # noqa: E402
from unilog_product_intelligence.domain.truth import (  # noqa: E402
    Source,
    SourceAuthority,
    SourceType,
)
from unilog_product_intelligence.enrichment.agent import (
    EvidenceGroundedEnrichmentAgent,  # noqa: E402
)
from unilog_product_intelligence.enrichment.models import (  # noqa: E402
    ReferenceAvailability,
)
from unilog_product_intelligence.enrichment.planner import AttributePlanner  # noqa: E402
from unilog_product_intelligence.enrichment.reference import (  # noqa: E402
    ReferencePack,
    ReferenceType,
)
from unilog_product_intelligence.enrichment.service import EnrichmentService  # noqa: E402
from unilog_product_intelligence.enrichment.validation import ValidationPipeline  # noqa: E402
from unilog_product_intelligence.providers.factory import (  # noqa: E402
    ExecutionMode,
    build_provider,
)
from unilog_product_intelligence.providers.gemini import (  # noqa: E402
    GeminiConcurrencyLimiter,
    GeminiConfigurationError,
)
from unilog_product_intelligence.providers.gemini_router import GeminiRouter  # noqa: E402
from unilog_product_intelligence.retrieval.agents import (  # noqa: E402
    DiscoveryResult,
    ManufacturerDiscoveryAgent,
)
from unilog_product_intelligence.retrieval.core import (  # noqa: E402
    AsyncSourceFetcher,
    DomainCircuitBreaker,
    DomainResolver,
    EvidenceExtractor,
    ManufacturerProfile,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourcePolicy,
    SourceRecord,
    SourceVerifier,
    _host,
    _same_or_subdomain,
)
from unilog_product_intelligence.retrieval.manufacturer_registry import (  # noqa: E402
    ManufacturerRegistry,
)
from unilog_product_intelligence.retrieval.service import (
    ManufacturerIntelligenceService,  # noqa: E402
)
from unilog_product_intelligence.retrieval.source_discovery import (  # noqa: E402
    ProductSourceDiscoveryService,
)
from unilog_product_intelligence.validation.truth_audit import TruthAudit  # noqa: E402

# ── Default paths relative to project root ────────────────────────────────────
_DEFAULT_INPUT = _ROOT / "Unihack_ Sample Dataset - Input.csv"
_DEFAULT_OUTPUT = _ROOT / "delivery_output.csv"
_DEFAULT_SCHEMA = _ROOT / "docs" / "research" / "delivery-schema.json"


@dataclass(frozen=True)
class _RowJob:
    idx: int
    row: Any
    queued_at: datetime
    queued_perf: float


@dataclass
class _RowExecutionResult:
    idx: int
    row_num: int
    mpn: str
    manuf: str
    status_label: str
    blocker_label: str
    duration_ms: int
    delivery_row: list[Any]
    trace: dict[str, Any]
    error: str | None = None


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
        "--reference-root",
        default=None,
        help="Directory containing official UniHack reference files (default: search project root and data/reference)",
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        help="Skip live HTTP retrieval (use provider-only without live network fetching)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of concurrent product workers (default: 8 or PIPELINE_WORKERS)",
    )
    parser.add_argument(
        "--gemini-concurrency",
        type=int,
        default=None,
        help="Max concurrent Gemini requests (default: 5 or GEMINI_MAX_CONCURRENCY)",
    )
    return parser.parse_args()


def _build_pipeline(
    provider: object,
    truth_service: ProductTruthService,
    fetcher: SourceFetcher | AsyncSourceFetcher,
    source_disc: ProductSourceDiscoveryService,
    reference_pack: ReferencePack | None = None,
    *,
    live: bool = True,
) -> Phase65Pipeline:
    """Wire all services into a Phase65Pipeline with a working source_binding."""

    resolver = DomainResolver()
    disc_agent = ManufacturerDiscoveryAgent(provider=provider, resolver=resolver)  # type: ignore[arg-type]
    extractor = EvidenceExtractor(provider=provider)  # type: ignore[arg-type]
    mfg_service = ManufacturerIntelligenceService(fetcher=fetcher, extractor=extractor)
    planner = AttributePlanner(reference_pack=reference_pack)
    enrichment_service = EnrichmentService(
        planner=planner,
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
            c for c in disc.candidates if c.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
        )
        candidate_candidates = tuple(
            c for c in disc.candidates if c.status == SourceDecision.CANDIDATE_MANUFACTURER_SOURCE
        )
        if not verified_candidates and not candidate_candidates:
            return None

        profile_base_domains = tuple(c.domain for c in verified_candidates)
        # Enrich verified_domains from the static catalog — the discovery LLM may
        # return companion domains (e.g. learnwhirlpool.com) as CANDIDATE rather
        # than VERIFIED, but they are authoritative per our catalog.
        registry = ManufacturerRegistry()
        catalog_profile = registry.get_profile_by_domain(
            tuple(c.domain for c in verified_candidates + candidate_candidates)
        )
        if catalog_profile is not None:
            all_verified = frozenset(profile_base_domains) | frozenset(catalog_profile.domains)
        else:
            all_verified = frozenset(profile_base_domains)

        profile = ManufacturerProfile(
            manufacturer_id=mfg_name or "unknown",
            canonical_name=mfg_name or "unknown",
            verified_domains=tuple(all_verified),
            candidate_domains=tuple(c.domain for c in candidate_candidates),
        )
        candidates = source_disc.discover(product, profile, candidate_urls=disc.search_result_urls)
        if not candidates:
            return None
        best = candidates[0]
        best_domain = _host(best.url)
        is_secondary = (
            best.source_kind == SourceKind.DISTRIBUTOR_PRODUCT_PAGE
            or not profile.verified_domains
            or not any(_same_or_subdomain(best_domain, d) for d in profile.verified_domains)
        )

        # Ensure the discovered candidate is verified against the profile
        candidate_source = SourceRecord(
            canonical_url=best.url,
            original_url=best.url,
            source_kind=SourceKind.DISTRIBUTOR_PRODUCT_PAGE if is_secondary else best.source_kind,
            decision=SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE
            if is_secondary
            else SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
            manufacturer_id=profile.manufacturer_id,
            manufacturer_domain=best_domain,
            verified_domains=profile.verified_domains if not is_secondary else (),
            product_id=product.product_id,
        )
        if is_secondary:
            verified_source = SourceVerifier(SourcePolicy()).verify_secondary_source(
                candidate_source, profile
            )
            if verified_source.decision != SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE:
                return None
        else:
            verified_source = SourceVerifier(SourcePolicy()).verify_source(
                candidate_source, profile
            )
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


def _build_row_trace(
    idx: int,
    row: Any,
    row_num: int,
    mpn: str,
    manuf: str,
    result: Phase65Result,
    delivery: Any,
    headers: list[str],
    exec_mode_val: str,
    provider_model: str | None,
    ref_pack: ReferencePack,
    worker_id: str,
    queued_at: str,
    started_at: str,
    completed_at: str,
    queue_wait_ms: int,
    execution_ms: int,
) -> dict[str, Any]:
    # Phase 4 Telemetry
    p4_runs = result.phase4_job.runs if result.phase4_job else []
    p4_model = (
        p4_runs[0].model if p4_runs and p4_runs[0].model else (provider_model if p4_runs else None)
    )
    p4_calls = len(p4_runs)
    p4_input_tokens = (
        sum(r.input_tokens for r in p4_runs if r.input_tokens is not None)
        if any(r.input_tokens is not None for r in p4_runs)
        else None
    )
    p4_output_tokens = (
        sum(r.output_tokens for r in p4_runs if r.output_tokens is not None)
        if any(r.output_tokens is not None for r in p4_runs)
        else None
    )
    p4_cached_tokens = (
        sum(r.cached_tokens for r in p4_runs if r.cached_tokens is not None)
        if any(r.cached_tokens is not None for r in p4_runs)
        else None
    )
    p4_total_tokens = (
        sum(r.total_tokens for r in p4_runs if r.total_tokens is not None)
        if any(r.total_tokens is not None for r in p4_runs)
        else None
    )
    p4_latency_ms = (
        sum(r.latency_ms for r in p4_runs if r.latency_ms is not None)
        if any(r.latency_ms is not None for r in p4_runs)
        else None
    )
    p4_request_ids = [r.request_id for r in p4_runs if r.request_id]
    p4_error = next((r.error for r in p4_runs if r.error), None)
    p4_status = (
        "FAILED" if result.phase4_job and result.phase4_job.state.value == "failed" else "COMPLETED"
    )

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
        or (
            result.manufacturer_job.failure_reason.value
            if result.manufacturer_job and result.manufacturer_job.failure_reason
            else None
        )
        or (disc.failure_reason.value if disc and disc.failure_reason else None)
    )

    # Phase 6 Telemetry
    enrich = result.enrichment
    p6_calls = enrich.metrics.agent_calls if enrich else 0
    p6_input_tokens = (
        enrich.metrics.input_tokens if (enrich and enrich.metrics.input_tokens > 0) else None
    )
    p6_output_tokens = (
        enrich.metrics.output_tokens if (enrich and enrich.metrics.output_tokens > 0) else None
    )
    p6_cached_tokens = (
        enrich.metrics.cached_tokens if (enrich and enrich.metrics.cached_tokens > 0) else None
    )
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
        or getattr(getattr(c, "status", None), "value", None)
        in {"VERIFIED", "ENRICHED", "NORMALIZED"}
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

    return {
        "row_index": idx,
        "row_number": row_num,
        "product_id": f"row-{row_num}",
        "worker_id": worker_id,
        "queued_at": queued_at,
        "started_at": started_at,
        "completed_at": completed_at,
        "queue_wait_ms": queue_wait_ms,
        "execution_ms": execution_ms,
        "input_mpn": mpn,
        "input_manufacturer": manuf,
        "input_brand_fields": {
            "Unilog_Brand": str(row.raw_values.get("Unilog_Brand") or ""),
            "E1_Brand": str(row.raw_values.get("E1_Brand") or ""),
            "DIB_Brand": str(row.raw_values.get("DIB_Brand") or ""),
        },
        "resolved_manufacturer": (
            str(result.product_truth.identity.manufacturer.normalized_value or "")
            if (result.product_truth.identity and result.product_truth.identity.manufacturer)
            else ""
        ),
        "resolved_brand": (
            str(result.product_truth.identity.brand.normalized_value or "")
            if (result.product_truth.identity and result.product_truth.identity.brand)
            else ""
        ),
        "execution_mode": exec_mode_val,
        "duration_ms": execution_ms,
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
            "manufacturer_domain_verified": bool(
                [
                    c.domain
                    for c in (result.discovery.candidates if result.discovery else ())
                    if c.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
                ]
            ),
            "product_source_found": bool([s.uri for s in result.product_truth.sources if s.uri]),
            "product_source_verified": bool(
                result.manufacturer_job
                and result.manufacturer_job.source_is_product_verified
                and not result.manufacturer_job.secondary_source_used
            ),
            "secondary_source_used": bool(
                result.manufacturer_job and result.manufacturer_job.secondary_source_used
            ),
            "source_authority": (
                "SECONDARY"
                if (result.manufacturer_job and result.manufacturer_job.secondary_source_used)
                else "MANUFACTURER"
                if (result.manufacturer_job and result.manufacturer_job.source_is_product_verified)
                else "UNKNOWN"
            ),
            "selected_source_url": (
                result.manufacturer_job.verified_source_context.canonical_product_url
                if (result.manufacturer_job and result.manufacturer_job.verified_source_context)
                else (
                    [s.uri for s in result.product_truth.sources if s.uri][0]
                    if [s.uri for s in result.product_truth.sources if s.uri]
                    else None
                )
            ),
            "documents": list(
                result.manufacturer_job.verified_source_context.document_urls
                if (result.manufacturer_job and result.manufacturer_job.verified_source_context)
                else ()
            ),
            "retrieval_strategies_attempted": list(
                result.discovery.retrieval_strategies_attempted if result.discovery else ()
            ),
            "candidate_urls": list(result.discovery.search_result_urls if result.discovery else ()),
            "fetched_urls": [s.uri for s in result.product_truth.sources if s.uri],
            "source_decision": (
                result.manufacturer_job.state.value if result.manufacturer_job else "none"
            ),
            "source_status": (
                "success"
                if any(
                    s.authority
                    in {
                        SourceAuthority.HIGH,
                        SourceAuthority.AUTHORITATIVE,
                        SourceAuthority.SECONDARY,
                    }
                    for s in result.product_truth.sources
                )
                else "not_found"
            ),
            "identity_score": (
                result.manufacturer_job.identity_score
                if result.manufacturer_job and result.manufacturer_job.identity_score is not None
                else (
                    1.0
                    if any(
                        s.authority in {SourceAuthority.HIGH, SourceAuthority.AUTHORITATIVE}
                        for s in result.product_truth.sources
                    )
                    else 0.0
                )
            ),
            "mpn_match_type": (
                result.manufacturer_job.mpn_match_type if result.manufacturer_job else None
            ),
            "raw_mpn_match": (
                result.manufacturer_job.raw_mpn_match if result.manufacturer_job else None
            ),
            "transformed_mpn_match": (
                result.manufacturer_job.transformed_mpn_match if result.manufacturer_job else None
            ),
            "identity_rejection_reason": (
                result.manufacturer_job.identity_rejection_reason
                if result.manufacturer_job
                else None
            ),
            "identity_classification": (
                "STRONG_MATCH"
                if any(
                    s.authority
                    in {
                        SourceAuthority.HIGH,
                        SourceAuthority.AUTHORITATIVE,
                        SourceAuthority.SECONDARY,
                    }
                    for s in result.product_truth.sources
                )
                else None
            ),
            "evidence_count": len(result.product_truth.evidence),
            "digital_asset_count": len(result.product_truth.digital_assets),
            "asset_discovery_status": (
                result.manufacturer_job.asset_discovery_status if result.manufacturer_job else None
            ),
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
            "reference_availability": (
                result.enrichment.reference_availability.value
                if result.enrichment
                else ref_pack.availability.value
            ),
            "schema_source": (
                result.enrichment.attribute_plans[0].schema_source
                if (result.enrichment and result.enrichment.attribute_plans)
                else "FALLBACK_EXISTING_ATTRIBUTES"
            ),
            "allowed_uom_count": (
                sum(len(p.allowed_uom) for p in result.enrichment.attribute_plans)
                if result.enrichment
                else 0
            ),
            "lov_constraint_count": (
                sum(len(p.allowed_values) for p in result.enrichment.attribute_plans)
                if result.enrichment
                else 0
            ),
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
        "truth_audit": (
            TruthAudit().audit(result.evidence_packet).model_dump()
            if isinstance(getattr(result, "evidence_packet", None), ProductEvidencePacket)
            else None
        ),
    }


def _process_row_job(
    job: _RowJob,
    pipeline: Phase65Pipeline,
    truth_service: ProductTruthService,
    adapter: Phase65ResultDeliveryAdapter,
    headers: list[str],
    exec_mode_val: str,
    provider_model: str | None,
    ref_pack: ReferencePack,
) -> _RowExecutionResult:
    worker_id = threading.current_thread().name
    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()
    queue_wait_ms = int((started_perf - job.queued_perf) * 1000)

    row = job.row
    idx = job.idx
    row_num = row.row_number
    mpn = str(row.raw_values.get("Mfg_Part_Num") or "")
    manuf = str(row.raw_values.get("Part_Manuf") or "")

    try:
        source = Source(
            source_id=f"input-row-{row_num}",
            source_type=SourceType.SUPPLIED_INPUT,
            authority=SourceAuthority.HIGH,
        )
        product = truth_service.create_from_raw_input(f"row-{row_num}", row.raw_values, source)
        result = pipeline.run(product)
        delivery = adapter.to_record(result)
        delivery_row = delivery.as_row()

        completed_at = datetime.now(UTC)
        completed_perf = time.perf_counter()
        execution_ms = int((completed_perf - started_perf) * 1000)

        trace = _build_row_trace(
            idx=idx,
            row=row,
            row_num=row_num,
            mpn=mpn,
            manuf=manuf,
            result=result,
            delivery=delivery,
            headers=headers,
            exec_mode_val=exec_mode_val,
            provider_model=provider_model,
            ref_pack=ref_pack,
            worker_id=worker_id,
            queued_at=job.queued_at.isoformat(),
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat(),
            queue_wait_ms=queue_wait_ms,
            execution_ms=execution_ms,
        )

        return _RowExecutionResult(
            idx=idx,
            row_num=row_num,
            mpn=mpn,
            manuf=manuf,
            status_label=result.status.value,
            blocker_label=result.blocker or "",
            duration_ms=execution_ms,
            delivery_row=delivery_row,
            trace=trace,
            error=None,
        )
    except Exception as err:
        completed_at = datetime.now(UTC)
        completed_perf = time.perf_counter()
        execution_ms = int((completed_perf - started_perf) * 1000)
        error_str = f"{type(err).__name__}: {err}"

        error_trace = {
            "row_index": idx,
            "row_number": row_num,
            "product_id": f"row-{row_num}",
            "worker_id": worker_id,
            "queued_at": job.queued_at.isoformat(),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "queue_wait_ms": queue_wait_ms,
            "execution_ms": execution_ms,
            "input_mpn": mpn,
            "input_manufacturer": manuf,
            "final_status": "ERROR",
            "error": error_str,
        }

        return _RowExecutionResult(
            idx=idx,
            row_num=row_num,
            mpn=mpn,
            manuf=manuf,
            status_label="ERROR",
            blocker_label="ROW_EXECUTION_ERROR",
            duration_ms=execution_ms,
            delivery_row=[None] * len(headers),
            trace=error_trace,
            error=error_str,
        )


def main() -> None:
    args = _parse_args()
    settings = get_settings()

    input_path = Path(args.input)
    output_path = Path(args.output)
    schema_path = Path(args.schema)

    # ── Validate inputs ───────────────────────────────────────────────────────
    if not input_path.is_file():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    if not schema_path.is_file():
        print(f"ERROR: Schema file not found: {schema_path}", file=sys.stderr)
        print(
            "       Run: python -m unilog_product_intelligence.data.cli save-schema",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Resolve execution mode and provider (Fail-Closed on missing config) ───
    exec_mode = ExecutionMode.from_str(args.mode)
    gemini_concurrency = args.gemini_concurrency or settings.gemini_max_concurrency
    limiter = GeminiConcurrencyLimiter(
        max_concurrency=gemini_concurrency,
        requests_per_minute=settings.gemini_requests_per_minute,
    )

    try:
        provider = build_provider(exec_mode, settings=settings, limiter=limiter)
        if exec_mode == ExecutionMode.LIVE_GEMINI:
            provider = GeminiRouter(primary=provider, limiter=limiter)
    except GeminiConfigurationError as err:
        print(f"\nERROR: {err}\n", file=sys.stderr)
        print(
            "To run in LIVE_GEMINI mode, ensure GEMINI_API_KEY is set in your environment or .env file.",
            file=sys.stderr,
        )
        print(
            "Alternatively, use `--mode live-deterministic` for zero-cost deterministic execution.",
            file=sys.stderr,
        )
        sys.exit(1)

    provider_name = type(provider).__name__
    provider_model = getattr(provider, "model", "deterministic-evaluator")
    num_workers = args.workers or settings.pipeline_workers or 8

    print("=" * 65)
    print("UNILOG PRODUCT INTELLIGENCE PIPELINE")
    print("=" * 65)
    print(f"Execution Mode:     {exec_mode.value}")
    print(f"Provider:           {provider_name}")
    print(f"Model:              {provider_model}")
    print(f"Live Network:       {not args.no_live}")
    print(f"Product Workers:    {num_workers}")
    print(f"Gemini Concurrency: {gemini_concurrency}")
    print(f"Input:              {input_path}")
    print(f"Output:             {output_path}")
    print("=" * 65)

    # ── Discover Reference Pack ONCE at startup ─────────────────────────────
    ref_roots: list[Path] = []
    if args.reference_root:
        ref_roots.append(Path(args.reference_root))
    if settings.reference_root:
        ref_roots.append(Path(settings.reference_root))
    ref_roots.extend([_ROOT, _ROOT / "data" / "reference", _ROOT / "data"])

    ref_pack = ReferencePack.discover(ref_roots)

    uom_count = len(ref_pack.uom_standards.records) if ref_pack.uom_standards else 0
    dec_frac_count = (
        len(ref_pack.decimal_fractions.fraction_to_decimal) if ref_pack.decimal_fractions else 0
    )
    brand_count = len(ref_pack.manufacturer_brands.records) if ref_pack.manufacturer_brands else 0
    global_lov_count = len(ref_pack.global_lov.rules) if ref_pack.global_lov else 0
    cat_lovs = ", ".join(ref_pack.category_lovs.keys()) if ref_pack.category_lovs else "NONE"

    print("=" * 65)
    print("REFERENCE PACK STATUS")
    print("=" * 65)
    print(f"Overall Status:     {ref_pack.availability.value}")
    print(
        f"UOM Standards:      {ref_pack.status.get(ReferenceType.UOM_STANDARD, ReferenceAvailability.REFERENCE_UNAVAILABLE).value} ({uom_count} records)"
    )
    print(
        f"Decimal/Fraction:   {ref_pack.status.get(ReferenceType.DECIMAL_FRACTION, ReferenceAvailability.REFERENCE_UNAVAILABLE).value} ({dec_frac_count} mappings)"
    )
    print(
        f"Manufacturer/Brand: {ref_pack.status.get(ReferenceType.MANUFACTURER_BRAND, ReferenceAvailability.REFERENCE_UNAVAILABLE).value} ({brand_count} records)"
    )
    print(
        f"Global LOV:         {ref_pack.status.get(ReferenceType.GLOBAL_LOV, ReferenceAvailability.REFERENCE_UNAVAILABLE).value} ({global_lov_count} rules)"
    )
    print(
        f"Category LOVs:      {ref_pack.status.get(ReferenceType.CATEGORY_LOV, ReferenceAvailability.REFERENCE_UNAVAILABLE).value} ({cat_lovs})"
    )
    print(f"Discovered Files:   {len(ref_pack.files)}")
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
    circuit_breaker = DomainCircuitBreaker(
        max_consecutive_failures=settings.retrieval_max_domain_failures
    )
    fetcher = AsyncSourceFetcher(
        connect_timeout=settings.retrieval_connect_timeout,
        request_timeout=args.timeout or settings.retrieval_request_timeout,
        global_concurrency=settings.retrieval_global_concurrency,
        per_host_concurrency=settings.retrieval_per_host_concurrency,
        circuit_breaker=circuit_breaker,
    )
    source_disc = ProductSourceDiscoveryService(fetcher=fetcher, circuit_breaker=circuit_breaker)
    pipeline = _build_pipeline(
        provider,
        truth_service,
        fetcher,
        source_disc,
        reference_pack=ref_pack,
        live=not args.no_live,
    )

    # ── Open output CSV for incremental writing ───────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats = {"enriched": 0, "review_required": 0, "blocked": 0, "error": 0}
    traces: list[dict[str, Any]] = []

    with output_path.open("w", newline="", encoding="utf-8-sig") as out_file:
        writer = csv.writer(out_file, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        out_file.flush()

        max_in_flight = max(16, num_workers * 2)
        in_flight_futures: dict[int, concurrent.futures.Future[_RowExecutionResult]] = {}
        completed_buffer: dict[int, _RowExecutionResult] = {}
        next_write_idx = 1
        row_iter = iter(enumerate(rows, start=1))

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=num_workers, thread_name_prefix="pipeline-worker"
        ) as executor:

            def _submit_next() -> bool:
                try:
                    idx, row = next(row_iter)
                    job = _RowJob(
                        idx=idx,
                        row=row,
                        queued_at=datetime.now(UTC),
                        queued_perf=time.perf_counter(),
                    )
                    fut = executor.submit(
                        _process_row_job,
                        job,
                        pipeline,
                        truth_service,
                        adapter,
                        headers,
                        exec_mode.value,
                        provider_model,
                        ref_pack,
                    )
                    in_flight_futures[idx] = fut
                    return True
                except StopIteration:
                    return False

            # Pre-fill initial batch
            for _ in range(max_in_flight):
                if not _submit_next():
                    break

            # Drain tasks and flush in strictly sequential order
            while in_flight_futures:
                done, _ = concurrent.futures.wait(
                    in_flight_futures.values(),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                for fut in done:
                    done_idx = next(k for k, v in in_flight_futures.items() if v is fut)
                    del in_flight_futures[done_idx]
                    try:
                        res = fut.result()
                    except Exception as exc:
                        res = _RowExecutionResult(
                            idx=done_idx,
                            row_num=done_idx,
                            mpn="",
                            manuf="",
                            status_label="ERROR",
                            blocker_label="UNHANDLED_WORKER_EXCEPTION",
                            duration_ms=0,
                            delivery_row=[None] * len(headers),
                            trace={
                                "row_index": done_idx,
                                "final_status": "ERROR",
                                "error": str(exc),
                            },
                            error=str(exc),
                        )
                    completed_buffer[res.idx] = res
                    _submit_next()

                while next_write_idx in completed_buffer:
                    res = completed_buffer.pop(next_write_idx)
                    writer.writerow(res.delivery_row)
                    out_file.flush()

                    if res.error:
                        stats["error"] += 1
                        label = (
                            f"[{res.idx:4d}/{total}] Row {res.row_num:4d} | "
                            f"MPN={res.mpn[:30]:<30} | Manuf={res.manuf[:28]:<28}"
                        )
                        print(f"{label} | ERROR: {res.error} ({res.duration_ms}ms)")
                    else:
                        st_key = res.status_label.lower().replace(" ", "_")
                        stats[st_key] = stats.get(st_key, 0) + 1
                        blocker_str = f" [{res.blocker_label}]" if res.blocker_label else ""
                        label = (
                            f"[{res.idx:4d}/{total}] Row {res.row_num:4d} | "
                            f"MPN={res.mpn[:30]:<30} | Manuf={res.manuf[:28]:<28}"
                        )
                        print(f"{label} | {res.status_label}{blocker_str} ({res.duration_ms}ms)")

                    traces.append(res.trace)
                    next_write_idx += 1

    # ── Write traces JSON ─────────────────────────────────────────────────────
    traces_path = output_path.with_name(f"{output_path.stem}_traces.json")
    with traces_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "execution_mode": exec_mode.value,
                "provider": provider_name,
                "model": provider_model,
                "live_http_retrieval": not args.no_live,
                "workers": num_workers,
                "gemini_concurrency": gemini_concurrency,
                "timestamp": datetime.now(UTC).isoformat(),
                "total_rows": total,
                "stats": stats,
                "reference_pack": {
                    "availability": ref_pack.availability.value,
                    "discovered_files": len(ref_pack.files),
                    "roots": [str(r) for r in ref_roots],
                    "types": {
                        t.value: ref_pack.status.get(
                            t, ReferenceAvailability.REFERENCE_UNAVAILABLE
                        ).value
                        for t in ReferenceType
                    },
                    "counts": {
                        "uom_standards": uom_count,
                        "decimal_fractions": dec_frac_count,
                        "manufacturer_brands": brand_count,
                        "global_lov_rules": global_lov_count,
                        "category_lov_packs": len(ref_pack.category_lovs),
                    },
                },
                "traces": traces,
            },
            f,
            indent=2,
        )
    print(f"Traces: {traces_path}")

    if hasattr(fetcher, "close"):
        fetcher.close()

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
