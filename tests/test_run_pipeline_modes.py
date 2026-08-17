# ruff: noqa: E501
"""Unit tests for pipeline execution modes and fail-closed provider boundaries."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from unilog_product_intelligence.application.evaluation import (
    DeterministicEvaluationProvider,
)
from unilog_product_intelligence.config import Settings
from unilog_product_intelligence.domain.truth import (
    Source,
    SourceAuthority,
    SourceType,
)
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.providers.factory import (
    ExecutionMode,
    GeminiConfigurationError,
    build_provider,
)
from unilog_product_intelligence.providers.gemini import GeminiProvider


class MockGeminiSuccessProvider(LLMProvider):
    """Mock Gemini provider that returns valid structured JSON and rich telemetry."""

    def __init__(self, model: str = "gemini-3.5-flash-lite") -> None:
        self.model = model
        self.call_count = 0

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        if request.task == "product_understanding":
            output = '{"product_type": "Circular Saw Blade", "product_family": "Diablo", "semantic_features": ["12-inch", "carbide"], "evidence": [], "uncertain_items": []}'
        elif request.task == "classification":
            output = '{"candidates": [{"department": "Tools", "class_name": "Power Tool Accessories", "fine": "Saw Blades", "classpath": ["Tools", "Power Tool Accessories", "Saw Blades"]}], "selected_candidate": 0}'
        elif request.task == "attribute_extraction":
            output = '{"attributes": [], "missing_attributes": []}'
        elif request.task == "evidence_grounded_enrichment":
            output = '{"candidates": [], "unresolved_attributes": []}'
        else:
            output = "{}"

        return LLMResponse(
            output_text=output,
            model=self.model,
            input_tokens=150,
            output_tokens=75,
            cached_tokens=25,
            total_tokens=250,
            latency_ms=180,
            request_id=f"req-mock-{self.call_count}",
        )

    def generate_with_tools(self, request: LLMRequest, tools: list[dict[str, Any]]) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            output_text='{"candidates": [{"domain": "diablotools.com", "status": "verified_manufacturer_source", "source": "search", "reason": "verified"}]}',
            model=self.model,
            input_tokens=200,
            output_tokens=50,
            cached_tokens=0,
            total_tokens=250,
            latency_ms=300,
            request_id=f"req-search-{self.call_count}",
            tool_calls=1,
            search_call_count=1,
            search_result_count=3,
            search_result_urls=("https://diablotools.com/products/DCB518ASTS06G",),
        )


class MockGeminiFailingProvider(LLMProvider):
    """Mock Gemini provider that simulates an API error."""

    def __init__(self, model: str = "gemini-3.5-flash-lite") -> None:
        self.model = model

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("Gemini API 503: Service Unavailable")

    def generate_with_tools(self, request: LLMRequest, tools: list[dict[str, Any]]) -> LLMResponse:
        raise RuntimeError("Gemini Search 429: Rate Limit Exceeded")


def test_mode_selection_deterministic() -> None:
    """TEST A: LIVE_DETERMINISTIC mode selects DeterministicEvaluationProvider without Gemini."""
    provider = build_provider(ExecutionMode.LIVE_DETERMINISTIC)
    assert isinstance(provider, DeterministicEvaluationProvider)
    assert provider.model == "deterministic-evaluator"

    # String aliases
    assert isinstance(build_provider("live-deterministic"), DeterministicEvaluationProvider)
    assert isinstance(build_provider("deterministic"), DeterministicEvaluationProvider)


def test_mode_selection_gemini_with_valid_key() -> None:
    """TEST B: LIVE_GEMINI mode with configured key selects GeminiProvider."""
    settings = Settings(
        gemini_api_key=SecretStr("mock-key-12345"),
        gemini_model="gemini-3.5-flash-lite",
        live_external_execution=True,
    )
    provider = build_provider(ExecutionMode.LIVE_GEMINI, settings=settings)
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-3.5-flash-lite"
    assert provider.api_key_configured is True


def test_gemini_mode_fails_closed_when_key_missing() -> None:
    """TEST C: Missing Gemini configuration fails explicitly with GeminiConfigurationError."""
    settings = Settings(
        gemini_api_key=None,
        gemini_model="gemini-3.5-flash-lite",
    )
    with pytest.raises(GeminiConfigurationError, match="GEMINI_API_KEY is required"):
        build_provider(ExecutionMode.LIVE_GEMINI, settings=settings)

    # Empty string key must also fail closed
    empty_settings = Settings(
        gemini_api_key=SecretStr("   "),
        gemini_model="gemini-3.5-flash-lite",
    )
    with pytest.raises(GeminiConfigurationError, match="GEMINI_API_KEY is required"):
        build_provider(ExecutionMode.LIVE_GEMINI, settings=empty_settings)


def test_gemini_provider_failure_does_not_silently_fallback() -> None:
    """TEST D: Simulated Gemini provider failure surfaces error and does NOT silently fallback."""
    from unilog_product_intelligence.agents.orchestration import ProductOrchestrator
    from unilog_product_intelligence.application.phase65 import Phase65Pipeline
    from unilog_product_intelligence.application.product_truth import ProductTruthService
    from unilog_product_intelligence.enrichment.agent import EvidenceGroundedEnrichmentAgent
    from unilog_product_intelligence.enrichment.planner import AttributePlanner
    from unilog_product_intelligence.enrichment.service import EnrichmentService
    from unilog_product_intelligence.enrichment.validation import ValidationPipeline
    from unilog_product_intelligence.retrieval.agents import ManufacturerDiscoveryAgent
    from unilog_product_intelligence.retrieval.core import (
        DomainResolver,
        EvidenceExtractor,
        SourceFetcher,
    )
    from unilog_product_intelligence.retrieval.service import (
        ManufacturerIntelligenceService,
    )

    failing_provider = MockGeminiFailingProvider()
    truth_service = ProductTruthService()
    orchestrator = ProductOrchestrator(failing_provider, truth_service)
    resolver = DomainResolver()
    disc_agent = ManufacturerDiscoveryAgent(provider=failing_provider, resolver=resolver)
    fetcher = SourceFetcher(timeout=1.0, max_retries=0)
    extractor = EvidenceExtractor(provider=failing_provider)
    mfg_service = ManufacturerIntelligenceService(fetcher=fetcher, extractor=extractor)
    enrichment_service = EnrichmentService(
        planner=AttributePlanner(),
        agent=EvidenceGroundedEnrichmentAgent(provider=failing_provider),
        validator=ValidationPipeline(),
        truth_service=truth_service,
    )

    pipeline = Phase65Pipeline(
        orchestrator=orchestrator,
        discovery=disc_agent,
        manufacturer=mfg_service,
        enrichment=enrichment_service,
    )

    source = Source(
        source_id="input-1",
        source_type=SourceType.SUPPLIED_INPUT,
        authority=SourceAuthority.HIGH,
    )
    product = truth_service.create_from_raw_input(
        "test-prod-1",
        {"Mfg_Part_Num": "DCB518ASTS06G", "Part_Manuf": "Freud Inc", "Part_Desc": "Sanding Belt"},
        source,
    )

    result = pipeline.run(product)

    # Phase 4 failure must be recorded honestly
    assert result.phase4_job.state.value == "failed"
    assert result.blocker in {"GEMINI_FAILURE", "GEMINI_PROVIDER_5XX", "DOMAIN_UNRESOLVED", "SOURCE_NOT_FOUND"}
    # Must NOT have produced synthetic deterministic output under the guise of Gemini
    assert len(result.phase4_job.runs) > 0
    assert result.phase4_job.runs[0].status == "failed"


def test_telemetry_fields_preserved_in_llm_response() -> None:
    """TEST E: Telemetry (model, input_tokens, output_tokens, cached_tokens, latency_ms, request_id) is preserved."""
    provider = MockGeminiSuccessProvider(model="gemini-3.5-flash-lite")
    resp = provider.generate(LLMRequest(task="product_understanding", input_text="Sample text"))

    assert resp.model == "gemini-3.5-flash-lite"
    assert resp.input_tokens == 150
    assert resp.output_tokens == 75
    assert resp.cached_tokens == 25
    assert resp.total_tokens == 250
    assert resp.latency_ms == 180
    assert resp.request_id == "req-mock-1"


def test_phase5_search_vs_phase4_generation_telemetry_separated() -> None:
    """TEST F: Phase 5 search calls are separated from Phase 4 generation calls."""
    provider = MockGeminiSuccessProvider(model="gemini-3.5-flash-lite")

    # Phase 4 generation call
    gen_resp = provider.generate(LLMRequest(task="product_understanding", input_text="Saw Blade"))
    assert gen_resp.search_call_count == 0
    assert gen_resp.tool_calls == 0

    # Phase 5 tool-assisted retrieval call
    tool_resp = provider.generate_with_tools(
        LLMRequest(task="manufacturer_discovery", input_text="Search Diablo DCB518ASTS06G"),
        tools=[{"type": "google_search"}],
    )
    assert tool_resp.search_call_count == 1
    assert tool_resp.tool_calls == 1
    assert tool_resp.search_result_count == 3
    assert len(tool_resp.search_result_urls) == 1
