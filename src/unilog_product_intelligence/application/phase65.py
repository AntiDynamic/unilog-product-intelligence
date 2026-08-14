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
from unilog_product_intelligence.domain.truth import ProductTruth
from unilog_product_intelligence.enrichment.agent import evidence_references
from unilog_product_intelligence.enrichment.models import EnrichmentResult
from unilog_product_intelligence.enrichment.service import EnrichmentService
from unilog_product_intelligence.retrieval.agents import DiscoveryResult, ManufacturerDiscoveryAgent
from unilog_product_intelligence.retrieval.core import ManufacturerProfile, SourceRecord
from unilog_product_intelligence.retrieval.service import (
    ManufacturerIntelligenceService,
    ManufacturerJob,
    ManufacturerJobState,
)


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
    status: Phase65Status
    blocker: str | None = None


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
        if phase4_job.state == JobState.FAILED:
            return Phase65Result(
                product_truth=product,
                phase4_job=phase4_job,
                status=Phase65Status.BLOCKED,
                blocker="GEMINI_FAILURE",
            )

        discovery_result: DiscoveryResult | None = None
        manufacturer_job: ManufacturerJob | None = None
        if not evidence_references(product):
            manufacturer_name = _identity_value(product, "manufacturer") or ""
            mpn = _identity_value(product, "manufacturer_part_number")
            try:
                discovery_result = self.discovery.discover(
                    manufacturer_id=manufacturer_name,
                    manufacturer_name=manufacturer_name,
                    mpn=mpn,
                    description=str(product.raw_value("Part_Desc") or ""),
                )
            except Exception:
                return Phase65Result(
                    product_truth=product,
                    phase4_job=phase4_job,
                    status=Phase65Status.BLOCKED,
                    blocker="GEMINI_FAILURE",
                )
            if not discovery_result.candidates:
                return Phase65Result(
                    product_truth=product,
                    phase4_job=phase4_job,
                    discovery=discovery_result,
                    status=Phase65Status.REVIEW_REQUIRED,
                    blocker="DOMAIN_UNRESOLVED",
                )
            if self.source_binding is None:
                return Phase65Result(
                    product_truth=product,
                    phase4_job=phase4_job,
                    discovery=discovery_result,
                    status=Phase65Status.REVIEW_REQUIRED,
                    blocker="SOURCE_NOT_FOUND",
                )
            binding = self.source_binding(product, discovery_result)
            if binding is None:
                return Phase65Result(
                    product_truth=product,
                    phase4_job=phase4_job,
                    discovery=discovery_result,
                    status=Phase65Status.REVIEW_REQUIRED,
                    blocker="SOURCE_NOT_FOUND",
                )
            source, profile = binding
            product, manufacturer_job = self.manufacturer.process(
                product, source, profile, refresh=refresh
            )
            if manufacturer_job.state != ManufacturerJobState.COMPLETED:
                return Phase65Result(
                    product_truth=product,
                    phase4_job=phase4_job,
                    discovery=discovery_result,
                    manufacturer_job=manufacturer_job,
                    status=Phase65Status.REVIEW_REQUIRED,
                    blocker=_manufacturer_blocker(manufacturer_job),
                )
            if not evidence_references(product):
                return Phase65Result(
                    product_truth=product,
                    phase4_job=phase4_job,
                    discovery=discovery_result,
                    manufacturer_job=manufacturer_job,
                    status=Phase65Status.REVIEW_REQUIRED,
                    blocker="EVIDENCE_NOT_FOUND",
                )

        enrichment_result = self.enrichment.enrich(product)
        status = (
            Phase65Status.ENRICHED
            if enrichment_result.status.value == "ENRICHED"
            else Phase65Status.BLOCKED
            if enrichment_result.status.value == "BLOCKED"
            else Phase65Status.REVIEW_REQUIRED
        )
        return Phase65Result(
            product_truth=enrichment_result.product_truth,
            phase4_job=phase4_job,
            discovery=discovery_result,
            manufacturer_job=manufacturer_job,
            enrichment=enrichment_result,
            status=status,
            blocker=enrichment_result.error,
        )


def _identity_value(product: ProductTruth, field: str) -> str | None:
    identity = getattr(product.identity, field, None)
    if identity is None:
        return None
    return str(identity.normalized_value or identity.raw_value or "") or None


def _manufacturer_blocker(job: ManufacturerJob) -> str:
    if job.error in {"rejected", "non_authoritative"}:
        return "SOURCE_REJECTED"
    if job.error == "source_not_relevant_to_product":
        return "SOURCE_NOT_FOUND"
    if job.error in {"http_error", "timeout", "failed", "transient_fetch_failure"}:
        return "SOURCE_FETCH_FAILED"
    return "EVIDENCE_NOT_FOUND" if job.state == ManufacturerJobState.COMPLETED else "OTHER"
