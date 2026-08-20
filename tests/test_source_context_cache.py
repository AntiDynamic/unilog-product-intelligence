"""Tests for VerifiedProductSourceContext cache-key inclusion and Phase65 forwarding."""

from __future__ import annotations

import pytest

from unilog_product_intelligence.agents.orchestration import (
    JobState,
    ProductJob,
    ProductOrchestrator,
)
from unilog_product_intelligence.application.phase65 import Phase65Pipeline
from unilog_product_intelligence.domain.source_context import VerifiedProductSourceContext
from unilog_product_intelligence.domain.truth import ProductTruth, RawInputField
from unilog_product_intelligence.enrichment.agent import EvidenceGroundedEnrichmentAgent
from unilog_product_intelligence.enrichment.models import (
    Applicability,
    AttributePlan,
    EnrichmentDecision,
    EnrichmentResult,
    EnrichmentStatus,
    EvidenceReference,
    FinalAttributeStatus,
    PublicationState,
)
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.retrieval.agents import DiscoveryResult, ManufacturerDiscoveryAgent
from unilog_product_intelligence.retrieval.core import (
    DomainCandidate,
    DomainResolver,
    ManufacturerProfile,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourceRecord,
)
from unilog_product_intelligence.retrieval.service import (
    ManufacturerIntelligenceService,
    ManufacturerJob,
    ManufacturerJobState,
)


class DummyLLMProvider(LLMProvider):
    """Dummy concrete LLMProvider for testing."""

    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(output_text="", model="dummy")


def _make_fixture_data() -> tuple[ProductTruth, list[AttributePlan], list[EvidenceReference]]:
    product = ProductTruth(
        product_id="test-prod-100",
        raw_inputs=[
            RawInputField(field_name="Mfg_Part_Num", raw_value="MPN100", source_id="input-1"),
        ],
    )
    plan = AttributePlan(
        product_id="test-prod-100",
        attribute_id="attr-diam",
        attribute_name="Diameter",
        current_status=FinalAttributeStatus.MISSING,
        reason="planning",
        enrichment_required=EnrichmentDecision.ENRICH,
        applicability=Applicability.REQUIRED,
    )
    evidence = EvidenceReference(
        evidence_id="ev-1",
        source_id="src-1",
        source_type="MANUFACTURER_PAGE",
        evidence_text="Diameter: 5 in",
    )
    return product, [plan], [evidence]


def test_cache_key_changes_with_source_context_fields() -> None:
    product, plans, evidence = _make_fixture_data()

    ctx_a = VerifiedProductSourceContext(
        product_id="test-prod-100",
        canonical_product_url="https://example.com/p/MPN100",
        source_id="src-1",
        source_authority="AUTHORITATIVE",
        source_type="MANUFACTURER_PAGE",
        page_title="Product A",
        page_text="Diameter: 5 in",
    )
    ctx_b = VerifiedProductSourceContext(
        product_id="test-prod-100",
        canonical_product_url="https://example.com/p/MPN100",
        source_id="src-1",
        source_authority="AUTHORITATIVE",
        source_type="MANUFACTURER_PAGE",
        page_title="Product B",
        page_text="Diameter: 5 in",
    )
    ctx_a_clone = VerifiedProductSourceContext(
        product_id="test-prod-100",
        canonical_product_url="https://example.com/p/MPN100",
        source_id="src-1",
        source_authority="AUTHORITATIVE",
        source_type="MANUFACTURER_PAGE",
        page_title="Product A",
        page_text="Diameter: 5 in",
    )

    key_a = EvidenceGroundedEnrichmentAgent.cache_key(
        product, plans, evidence, "gemini-3.5-flash-lite", "phase6-v1", source_context=ctx_a
    )
    key_b = EvidenceGroundedEnrichmentAgent.cache_key(
        product, plans, evidence, "gemini-3.5-flash-lite", "phase6-v1", source_context=ctx_b
    )
    key_a_clone = EvidenceGroundedEnrichmentAgent.cache_key(
        product, plans, evidence, "gemini-3.5-flash-lite", "phase6-v1", source_context=ctx_a_clone
    )

    assert key_a != key_b, "Cache key must differ when page_title changes!"
    assert key_a == key_a_clone, "Cache key must be deterministic for identical context data!"


def test_cache_key_does_not_ignore_structured_fact_changes() -> None:
    product, plans, evidence = _make_fixture_data()

    ctx_fact_5 = VerifiedProductSourceContext(
        product_id="test-prod-100",
        canonical_product_url="https://example.com/p/MPN100",
        source_id="src-1",
        source_authority="AUTHORITATIVE",
        source_type="MANUFACTURER_PAGE",
        structured_facts=[{"attribute": "Diameter", "raw_value": "5 in"}],
    )
    ctx_fact_6 = VerifiedProductSourceContext(
        product_id="test-prod-100",
        canonical_product_url="https://example.com/p/MPN100",
        source_id="src-1",
        source_authority="AUTHORITATIVE",
        source_type="MANUFACTURER_PAGE",
        structured_facts=[{"attribute": "Diameter", "raw_value": "6 in"}],
    )

    key_5 = EvidenceGroundedEnrichmentAgent.cache_key(
        product, plans, evidence, "gemini-3.5-flash-lite", "phase6-v1", source_context=ctx_fact_5
    )
    key_6 = EvidenceGroundedEnrichmentAgent.cache_key(
        product, plans, evidence, "gemini-3.5-flash-lite", "phase6-v1", source_context=ctx_fact_6
    )

    assert key_5 != key_6, "Cache key must differ when structured facts change!"


def test_phase65_always_forwards_source_context() -> None:
    received_source_context: list[VerifiedProductSourceContext | None] = []

    class CapturingEnrichmentService:
        def enrich(
            self,
            product: ProductTruth,
            *,
            refresh: bool = False,
            source_context: VerifiedProductSourceContext | None = None,
            evidence_packet: object | None = None,
        ) -> EnrichmentResult:
            received_source_context.append(source_context)
            return EnrichmentResult(
                product_id=product.product_id,
                product_truth=product,
                candidates=(),
                status=EnrichmentStatus.ENRICHED,
                publication_state=PublicationState.READY,
            )

    class MockOrchestrator(ProductOrchestrator):
        def run(self, product: ProductTruth) -> tuple[ProductTruth, ProductJob]:
            return product, ProductJob(
                job_id="job-p4",
                product_id=product.product_id,
                state=JobState.CANDIDATES_ACCEPTED,
            )

    class MockDiscovery(ManufacturerDiscoveryAgent):
        def discover(self, *args: object, **kwargs: object) -> DiscoveryResult:
            return DiscoveryResult(
                candidates=[
                    DomainCandidate(
                        domain="example.com",
                        source="catalog",
                        reason="verified",
                        status=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                    )
                ]
            )

    ctx = VerifiedProductSourceContext(
        product_id="prod-1",
        canonical_product_url="https://example.com/p/1",
        source_id="src-1",
        source_authority="AUTHORITATIVE",
        source_type="MANUFACTURER_PAGE",
        page_title="Example Title",
    )
    job = ManufacturerJob(
        job_id="job-1",
        product_id="prod-1",
        state=ManufacturerJobState.COMPLETED,
        verified_source_context=ctx,
    )

    class MockMfgService(ManufacturerIntelligenceService):
        def process(
            self, product: ProductTruth, *args: object, **kwargs: object
        ) -> tuple[ProductTruth, ManufacturerJob]:
            return product, job

    dummy_provider = DummyLLMProvider()
    fetcher = SourceFetcher()
    pipeline = Phase65Pipeline(
        orchestrator=MockOrchestrator(dummy_provider),
        discovery=MockDiscovery(dummy_provider, DomainResolver()),
        manufacturer=MockMfgService(fetcher=fetcher),
        enrichment=CapturingEnrichmentService(),  # type: ignore[arg-type]
        source_binding=lambda prod, disc: (
            SourceRecord(
                canonical_url="https://example.com/p/1",
                original_url="https://example.com/p/1",
                source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
                decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                manufacturer_id="mfg-1",
                manufacturer_domain="example.com",
            ),
            ManufacturerProfile(
                manufacturer_id="mfg-1", canonical_name="mfg-1", verified_domains=("example.com",)
            ),
        ),
    )

    product = ProductTruth(product_id="prod-1")
    pipeline.run(product)

    assert len(received_source_context) == 1
    assert received_source_context[0] is ctx, "Phase65 must forward source_context to enrichment!"


def test_no_silent_typeerror_fallback() -> None:
    calls: list[str] = []

    class FailingEnrichmentService:
        def enrich(
            self,
            product: ProductTruth,
            *,
            refresh: bool = False,
            source_context: VerifiedProductSourceContext | None = None,
            evidence_packet: object | None = None,
        ) -> EnrichmentResult:
            calls.append("enrich_called")
            # Intentionally raise internal TypeError
            raise TypeError("Real internal TypeError inside enrichment algorithm")

    class MockOrchestrator(ProductOrchestrator):
        def run(self, product: ProductTruth) -> tuple[ProductTruth, ProductJob]:
            return product, ProductJob(
                job_id="job-p4",
                product_id=product.product_id,
                state=JobState.CANDIDATES_ACCEPTED,
            )

    dummy_provider = DummyLLMProvider()
    fetcher = SourceFetcher()
    pipeline = Phase65Pipeline(
        orchestrator=MockOrchestrator(dummy_provider),
        discovery=ManufacturerDiscoveryAgent(dummy_provider, DomainResolver()),
        manufacturer=ManufacturerIntelligenceService(fetcher=fetcher),
        enrichment=FailingEnrichmentService(),  # type: ignore[arg-type]
    )

    product = ProductTruth(product_id="prod-1")
    with pytest.raises(TypeError, match="Real internal TypeError inside enrichment algorithm"):
        pipeline.run(product)

    assert len(calls) == 1, (
        "Enrichment must be called exactly once; TypeError must NOT trigger a second fallback call!"
    )
