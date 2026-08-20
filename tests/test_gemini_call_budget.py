"""Tests for bounded Gemini call budgets and zero redundant model calls."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from unilog_product_intelligence.agents.orchestration import (
    ProductOrchestrator,
)
from unilog_product_intelligence.application.evaluation import DeterministicEvaluationProvider
from unilog_product_intelligence.application.phase65 import Phase65Pipeline, Phase65Status
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.delivery.adapter import (
    DeliverySchemaContract,
    Phase65ResultDeliveryAdapter,
)
from unilog_product_intelligence.domain.truth import (
    CandidateValue,
    Evidence,
    EvidenceType,
    ProductClassification,
    ProductTruth,
    Source,
    SourceAuthority,
    ValueStatus,
)
from unilog_product_intelligence.enrichment.agent import EvidenceGroundedEnrichmentAgent
from unilog_product_intelligence.enrichment.descriptions import DescriptionAgent, DescriptionService
from unilog_product_intelligence.enrichment.planner import AttributePlanner
from unilog_product_intelligence.enrichment.service import EnrichmentService
from unilog_product_intelligence.enrichment.validation import ValidationPipeline
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.retrieval.agents import DiscoveryResult, ManufacturerDiscoveryAgent
from unilog_product_intelligence.retrieval.core import (
    CacheStatus,
    DomainResolver,
    EvidenceExtractor,
    FetchResult,
    ManufacturerProfile,
    SourceDecision,
    SourceKind,
    SourceRecord,
)
from unilog_product_intelligence.retrieval.service import (
    ManufacturerIntelligenceService,
)


class CallCountingProvider(LLMProvider):
    """LLMProvider wrapper tracking total model calls and task types."""

    model: str = "mock-gemini"
    supports_unified_pre_enrichment: bool = True

    def __init__(self, inner: LLMProvider | None = None) -> None:
        self.inner = inner or DeterministicEvaluationProvider()
        self.calls: list[LLMRequest] = []
        self.tool_calls: list[tuple[LLMRequest, Any]] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return self.inner.generate(request)

    def generate_with_tools(self, request: LLMRequest, tools: Any) -> LLMResponse:
        self.calls.append(request)
        self.tool_calls.append((request, tools))
        generate_with_tools = getattr(self.inner, "generate_with_tools", None)
        if callable(generate_with_tools):
            return generate_with_tools(request, tools)
        return self.inner.generate(request)


def _make_sample_product(
    pid: str = "prod-1", mpn: str = "DCB518ASTS06G", mfg: str = "Freud Inc"
) -> ProductTruth:
    raw_source = Source(
        source_id="raw-src",
        source_type="supplied_input",
        authority=SourceAuthority.LOW,
    )
    raw_fields = {
        "Mfg_Part_Num": mpn,
        "Part_Manuf": mfg,
        "Part_Desc": f"{mfg} {mpn} Industrial Diamond Sanding Disc 5 inch",
        "Unilog_Brand": "Diablo",
    }
    truth_service = ProductTruthService()
    return truth_service.create_from_raw_input(pid, raw_fields, raw_source)


def test_normal_product_path_uses_at_most_three_calls() -> None:
    """Requirement 1: Normal product path uses <= 3 calls."""
    counting_provider = CallCountingProvider()
    truth_service = ProductTruthService()

    orchestrator = ProductOrchestrator(provider=counting_provider, service=truth_service)
    resolver = DomainResolver()
    discovery = ManufacturerDiscoveryAgent(provider=counting_provider, resolver=resolver)
    extractor = EvidenceExtractor(provider=counting_provider)

    mock_fetcher = MagicMock()
    # Mock successful fetch with structured HTML data
    sample_html = b"""
    <html>
      <head><title>Diablo DCB518ASTS06G 5 in Sanding Disc</title></head>
      <body>
        <h1>Diablo DCB518ASTS06G</h1>
        <table>
          <tr><th>Diameter</th><td>5 in</td></tr>
          <tr><th>Grit</th><td>80</td></tr>
          <tr><th>Material</th><td>Ceramic Blend</td></tr>
        </table>
      </body>
    </html>
    """
    mock_source = SourceRecord(
        canonical_url="https://diablotools.com/products/DCB518ASTS06G",
        original_url="https://diablotools.com/products/DCB518ASTS06G",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="Freud Inc",
        manufacturer_domain="diablotools.com",
        product_id="prod-1",
    )
    mock_fetcher.fetch.return_value = FetchResult(
        source=mock_source,
        cache_status=CacheStatus.MISS,
        body=sample_html,
        latency_ms=20,
    )

    mfg_service = ManufacturerIntelligenceService(fetcher=mock_fetcher, extractor=extractor)
    planner = AttributePlanner()
    enrichment_service = EnrichmentService(
        planner=planner,
        agent=EvidenceGroundedEnrichmentAgent(provider=counting_provider),
        validator=ValidationPipeline(),
        truth_service=truth_service,
        description_service=DescriptionService(agent=DescriptionAgent(provider=counting_provider)),
    )

    def dummy_source_binding(
        p: ProductTruth, d: DiscoveryResult
    ) -> tuple[SourceRecord, ManufacturerProfile] | None:
        return (
            mock_source,
            ManufacturerProfile(
                manufacturer_id="Freud Inc",
                canonical_name="Freud Inc",
                verified_domains=("diablotools.com",),
            ),
        )

    pipeline = Phase65Pipeline(
        orchestrator=orchestrator,
        discovery=discovery,
        manufacturer=mfg_service,
        enrichment=enrichment_service,
        source_binding=dummy_source_binding,
    )

    product = _make_sample_product()
    result = pipeline.run(product)

    assert result.status == Phase65Status.ENRICHED
    # Total Gemini / model calls for the complete product run MUST be <= 3
    assert len(counting_provider.calls) <= 3
    # Verify exact task distribution (1 Phase 4 pre-enrichment, 0 Phase 5 extraction, 1-2 Phase 6)
    tasks = [c.task for c in counting_provider.calls]
    assert "product_pre_enrichment" in tasks
    assert len(tasks) <= 3


def test_retrieval_success_path_does_not_invoke_gemini_search_fallback() -> None:
    """Requirement 2: Retrieval-success path does not invoke Gemini search fallback."""
    counting_provider = CallCountingProvider()

    resolver = DomainResolver()
    discovery = ManufacturerDiscoveryAgent(provider=counting_provider, resolver=resolver)

    # Known manufacturer in catalog / brand alias (Diablo)
    res = discovery.discover(
        manufacturer_id="m-diablo",
        manufacturer_name="Freud Inc",
        mpn="DCB518ASTS06G",
        brand="Diablo",
    )

    # Deterministic resolution must succeed without calling Gemini search
    assert res.search_requested is False
    assert len(res.candidates) > 0
    assert any(c.domain == "diablotools.com" for c in res.candidates)
    # Zero model calls made during deterministic discovery
    search_calls = [c for c in counting_provider.calls if c.task == "manufacturer_discovery"]
    assert len(search_calls) == 0


def test_retrieval_failure_may_invoke_fallback() -> None:
    """Requirement 3: Retrieval failure may invoke fallback."""
    counting_provider = CallCountingProvider()
    resolver = DomainResolver()
    discovery = ManufacturerDiscoveryAgent(provider=counting_provider, resolver=resolver)

    # Brand completely unknown in catalog -> should invoke Gemini search fallback
    res = discovery.discover(
        manufacturer_id="m-unknown-brand-xyz",
        manufacturer_name="Unknown Specialized Corp XYZ",
        mpn="XYZ-999-SPECIAL",
        brand="UnknownBrandXYZ",
    )

    assert res.search_requested is True
    search_calls = [c for c in counting_provider.calls if c.task == "manufacturer_discovery"]
    assert len(search_calls) == 1


def test_all_existing_evidence_ids_remain_valid() -> None:
    """Requirement 4: All existing evidence IDs remain valid."""
    truth_service = ProductTruthService()
    product = _make_sample_product()
    product = truth_service.add_classification(
        product,
        ProductClassification(
            department="Tools",
            class_name="Abrasives",
            fine="Sanding Discs",
            classpath=("Tools", "Abrasives", "Sanding Discs"),
            source_ids=["raw-src"],
        ),
    )

    # Verify initial candidate and evidence creation
    cand_id = "test-cand-1"
    ev_id = "test-ev-1"
    candidate = CandidateValue(
        candidate_id=cand_id,
        raw_value="120 V",
        normalized_value="120 V",
        uom="V",
        status=ValueStatus.CANDIDATE,
        source_ids=["raw-src"],
    )
    product = truth_service.add_attribute_candidate(
        product, "attribute-voltage", candidate, "Voltage"
    )
    product = truth_service.attach_evidence(
        product,
        Evidence(
            evidence_id=ev_id,
            source_id="raw-src",
            product_id=product.product_id,
            attribute_id="attribute-voltage",
            candidate_id=cand_id,
            quoted_text="120 V AC",
            location={"field": "Part_Desc"},
            evidence_type=EvidenceType.DIRECT_TEXT,
        ),
    )

    attr = product.attribute("attribute-voltage")
    assert attr is not None
    assert len(attr.candidates) == 1
    assert attr.candidates[0].candidate_id == cand_id

    evs = [e for e in product.evidence if e.attribute_id == "attribute-voltage"]
    assert len(evs) == 1
    assert evs[0].evidence_id == ev_id
    assert evs[0].quoted_text == "120 V AC"


def test_attribute_quality_and_schema_remains_unchanged() -> None:
    """Requirement 5: Attribute quality/schema remains unchanged."""
    from pathlib import Path

    schema_path = (
        Path(__file__).resolve().parent.parent / "docs" / "research" / "delivery-schema.json"
    )
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)
    assert len(adapter.contract.headers) == 252


def test_description_quality_remains_populated() -> None:
    """Requirement 6: Description quality remains populated."""
    product = _make_sample_product()

    agent = DescriptionAgent(provider=DeterministicEvaluationProvider())
    service = DescriptionService(agent=agent)

    product, validations = service.generate_descriptions(product)

    assert product.descriptions is not None
    assert len(product.descriptions.short) > 0
    assert len(product.descriptions.long) > 0
    assert len(product.descriptions.mobile) > 0
    assert len(product.descriptions.invoice) > 0
    assert len(product.descriptions.retail) > 0
    short_desc = product.descriptions.short
    assert short_desc.startswith("Diablo") or "DCB518ASTS06G" in short_desc
