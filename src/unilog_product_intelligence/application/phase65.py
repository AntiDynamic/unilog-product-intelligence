"""Composition-owned Phase 6.5 seam joining the existing Phase 4, 5, and 6 services."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from unilog_product_intelligence.agents.orchestration import (
    JobState,
    ProductJob,
    ProductOrchestrator,
)
from unilog_product_intelligence.application.brand_resolver import BrandManufacturerResolver
from unilog_product_intelligence.application.scale import FailureCategory, classify_429
from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.domain.truth import ProductTruth
from unilog_product_intelligence.enrichment.agent import evidence_references
from unilog_product_intelligence.enrichment.models import EnrichmentResult
from unilog_product_intelligence.enrichment.service import EnrichmentService
from unilog_product_intelligence.retrieval.agents import DiscoveryResult, ManufacturerDiscoveryAgent
from unilog_product_intelligence.retrieval.core import (
    ManufacturerProfile,
    Phase5FailureReason,
    SourceDecision,
    SourceRecord,
)
from unilog_product_intelligence.retrieval.service import (
    ManufacturerIntelligenceService,
    ManufacturerJob,
    ManufacturerJobState,
)

_brand_resolver = BrandManufacturerResolver()


class Phase65Status(StrEnum):
    ENRICHED = "ENRICHED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


class Phase65Result(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_truth: ProductTruth
    phase4_job: ProductJob
    discovery: DiscoveryResult | None = None
    manufacturer_job: ManufacturerJob | None = None
    enrichment: EnrichmentResult | None = None
    evidence_packet: ProductEvidencePacket | None = None
    status: Phase65Status
    blocker: str | None = None
    phase5_error: str | None = None
    # Resolved manufacturer/brand after distributor masking removal
    resolved_manufacturer: str | None = None
    resolved_brand: str | None = None
    is_distributor_masked: bool = False


SourceBinding = Callable[
    [ProductTruth, DiscoveryResult], tuple[SourceRecord, ManufacturerProfile] | None
]


class Phase65Pipeline:
    """Reuse existing services in order; no provider or retrieval policy is duplicated here."""

    def __init__(
        self,
        orchestrator: ProductOrchestrator,
        discovery: ManufacturerDiscoveryAgent,
        manufacturer: ManufacturerIntelligenceService,
        enrichment: EnrichmentService,
        source_binding: SourceBinding | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.discovery = discovery
        self.manufacturer = manufacturer
        self.enrichment = enrichment
        self.source_binding = source_binding

    def run(self, product: ProductTruth, *, refresh: bool = False) -> Phase65Result:
        product, phase4_job = self.orchestrator.run(product)
        phase4_failed = phase4_job.state == JobState.FAILED

        discovery_result: DiscoveryResult | None = None
        manufacturer_job: ManufacturerJob | None = None
        blocker: str | None = "GEMINI_FAILURE" if phase4_failed else None
        phase5_error: str | None = None

        # Resolve real manufacturer/brand, removing distributor masking
        raw_manuf = str(product.raw_value("Part_Manuf") or "")
        raw_desc = str(product.raw_value("Part_Desc") or "")
        mpn = _identity_value(product, "manufacturer_part_number")
        resolved = _brand_resolver.resolve(raw_manuf, raw_desc, mpn=mpn)

        if not evidence_references(product):
            # Use resolved manufacturer name (strips distributor, maps to real maker)
            if resolved.is_distributor:
                manufacturer_name = resolved.manufacturer
                brand = resolved.brand or _extract_brand(product)
            else:
                manufacturer_name = (
                    _identity_value(product, "manufacturer")
                    or resolved.manufacturer
                    or ""
                )
                brand = _extract_brand(product) or resolved.brand
            try:
                discovery_result = self.discovery.discover(
                    manufacturer_id=manufacturer_name,
                    manufacturer_name=manufacturer_name,
                    mpn=mpn,
                    description=str(product.raw_value("Part_Desc") or ""),
                    brand=brand,
                )
            except Exception as error:
                phase5_error = _safe_failure_detail(error)
                provider = getattr(self.discovery, "provider", None)
                search_requested = callable(getattr(provider, "generate_with_tools", None))
                discovery_result = DiscoveryResult(
                    unresolved_reason=phase5_error,
                    search_requested=search_requested,
                )
                blocker = _gemini_blocker(error)
            else:
                if not discovery_result.candidates:
                    blocker = "DOMAIN_UNRESOLVED"
                elif self.source_binding is None:
                    blocker = "SOURCE_NOT_FOUND"
                else:
                    binding = self.source_binding(product, discovery_result)
                    provider = getattr(self.discovery, "provider", None)
                    live_search_enabled = bool(getattr(provider, "supports_live_web_search", False))
                    binding_is_secondary = (
                        binding is not None
                        and binding[0].decision == SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE
                    )
                    if (
                        (binding is None or binding_is_secondary or live_search_enabled)
                        and not discovery_result.search_requested
                        and hasattr(self.discovery, "search_fallback")
                    ):
                        fallback_result = self.discovery.search_fallback(
                            manufacturer_id=manufacturer_name,
                            manufacturer_name=manufacturer_name,
                            mpn=mpn,
                            description=str(product.raw_value("Part_Desc") or ""),
                            brand=brand,
                            existing_result=discovery_result,
                        )
                        if fallback_result.search_result_urls:
                            fallback_binding = self.source_binding(product, fallback_result)
                            if fallback_binding is not None:
                                fallback_is_secondary = (
                                    fallback_binding[0].decision
                                    == SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE
                                )
                                if binding is None or not fallback_is_secondary:
                                    binding = fallback_binding
                                    discovery_result = fallback_result

                    if binding is None:
                        blocker = "SOURCE_NOT_FOUND"
                    else:
                        source, profile = binding
                        product, manufacturer_job = self.manufacturer.process(
                            product, source, profile, refresh=refresh
                        )
                        if (
                            manufacturer_job.state != ManufacturerJobState.COMPLETED
                            and hasattr(self.manufacturer, "recover")
                        ):
                            cand_urls = getattr(discovery_result, "search_result_urls", ())
                            product, manufacturer_job = self.manufacturer.recover(
                                product, profile, manufacturer_job, candidate_urls=cand_urls
                            )
                        if manufacturer_job.state != ManufacturerJobState.COMPLETED:
                            blocker = _manufacturer_blocker(manufacturer_job)
        source_ctx = (
            manufacturer_job.verified_source_context if manufacturer_job is not None else None
        )
        evidence_pkt = (
            manufacturer_job.evidence_packet if manufacturer_job is not None else None
        )
        enrichment_result = self.enrichment.enrich(
            product,
            source_context=source_ctx,
            evidence_packet=evidence_pkt,
        )
        status = (
            Phase65Status.ENRICHED
            if enrichment_result.status.value == "ENRICHED"
            else Phase65Status.BLOCKED
            if enrichment_result.status.value == "BLOCKED"
            else Phase65Status.REVIEW_REQUIRED
        )
        if blocker and status == Phase65Status.ENRICHED:
            status = Phase65Status.REVIEW_REQUIRED
        return Phase65Result(
            product_truth=enrichment_result.product_truth,
            phase4_job=phase4_job,
            discovery=discovery_result,
            manufacturer_job=manufacturer_job,
            enrichment=enrichment_result,
            evidence_packet=evidence_pkt,
            status=status,
            blocker=blocker or enrichment_result.error,
            phase5_error=phase5_error,
            resolved_manufacturer=resolved.manufacturer if resolved else None,
            resolved_brand=resolved.brand if resolved else None,
            is_distributor_masked=resolved.is_distributor if resolved else False,
        )


def _gemini_blocker(error: Exception) -> str:
    status_code = getattr(error, "status_code", None)
    status_text = str(status_code)
    normalized_status = int(status_text) if status_text.isdigit() else None
    if normalized_status == 429:
        category = classify_429(error)
        return {
            FailureCategory.SEARCH_LIMIT: "GEMINI_SEARCH_LIMIT",
            FailureCategory.PROJECT_QUOTA: "GEMINI_PROVIDER_QUOTA",
            FailureCategory.RATE_LIMIT: "GEMINI_PROVIDER_429",
            FailureCategory.SPEND_LIMIT: "GEMINI_BILLING_FAILURE",
            FailureCategory.CAPACITY: "GEMINI_PROVIDER_5XX",
        }.get(category, "GEMINI_PROVIDER_429")
    if normalized_status in {401, 403}:
        return "GEMINI_AUTH_FAILURE"
    if normalized_status in {400, 422}:
        return "GEMINI_INVALID_REQUEST"
    if normalized_status == 404:
        return "GEMINI_MODEL_NOT_FOUND"
    if normalized_status is not None and normalized_status >= 500:
        return "GEMINI_PROVIDER_5XX"
    provider_code = str(getattr(error, "provider_code", "") or "").casefold()
    if "tool" in provider_code:
        return "GEMINI_TOOL_UNAVAILABLE"
    return "GEMINI_UNKNOWN_FAILURE"


def _safe_failure_detail(error: Exception) -> str:
    details = [f"discovery_failed:{type(error).__name__}"]
    status_code = getattr(error, "status_code", None)
    provider_code = getattr(error, "provider_code", None)
    if isinstance(status_code, int):
        details.append(str(status_code))
    if isinstance(provider_code, str) and provider_code:
        details.append(provider_code[:80])
    return ":".join(details)


_PLACEHOLDER_BRANDS = {
    "",
    "-",
    "-- unbranded --",
    "-- no unilog brand --",
    "-- no dib brand --",
    "-- unassigned --",
    "none",
    "n/a",
    "null",
}


def _extract_brand(product: ProductTruth) -> str | None:
    brand = _identity_value(product, "brand")
    if brand and brand.casefold() not in _PLACEHOLDER_BRANDS:
        return brand
    for key in ("Unilog_Brand", "E1_Brand", "DIB_Brand", "Brand", "Brand_Name", "brand"):
        raw = product.raw_value(key)
        if raw and str(raw).strip() and str(raw).strip().casefold() not in _PLACEHOLDER_BRANDS:
            return str(raw).strip()
    return None


def _identity_value(product: ProductTruth, field: str) -> str | None:
    identity = getattr(product.identity, field, None)
    if identity is None:
        return None
    return str(identity.normalized_value or identity.raw_value or "") or None


def _manufacturer_blocker(job: ManufacturerJob) -> str:
    if job.error in {"rejected", "non_authoritative"}:
        return "SOURCE_REJECTED"
    if (job.error or "").startswith("source_not_relevant_to_product"):
        return "SOURCE_NOT_FOUND"
    if job.error in {"http_error", "timeout", "failed", "transient_fetch_failure"}:
        return "SOURCE_FETCH_FAILED"
    if job.failure_reason == Phase5FailureReason.SOURCE_FETCH_FAILED:
        return "SOURCE_FETCH_FAILED"
    if job.failure_reason in {
        Phase5FailureReason.PRODUCT_IDENTITY_MISMATCH,
        Phase5FailureReason.PRODUCT_SOURCE_NOT_FOUND,
    }:
        return "SOURCE_NOT_FOUND"
    if job.failure_reason == Phase5FailureReason.DOMAIN_UNVERIFIED:
        return "SOURCE_REJECTED"
    return "EVIDENCE_NOT_FOUND" if job.state == ManufacturerJobState.COMPLETED else "OTHER"
