"""Focused tests for the connected Phase 4 -> Phase 5 -> Phase 6 seam."""

import json

import pytest

from unilog_product_intelligence.agents.orchestration import JobState, ProductJob
from unilog_product_intelligence.application.phase65 import Phase65Pipeline, Phase65Status
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.truth import (
    AssessmentMetadata,
    CandidateValue,
    Evidence,
    EvidenceType,
    Source,
    SourceAuthority,
    SourceType,
    ValueStatus,
)
from unilog_product_intelligence.enrichment.agent import evidence_references
from unilog_product_intelligence.enrichment.models import (
    EnrichmentResult,
    EnrichmentStatus,
    PublicationState,
)
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.retrieval import (
    DomainResolver,
    ManufacturerProfile,
    SourceRecord,
)
from unilog_product_intelligence.retrieval.agents import (
    DiscoveryResult,
    ManufacturerDiscoveryAgent,
)
from unilog_product_intelligence.retrieval.core import (
    DomainCandidate,
    SourceDecision,
    SourceKind,
)
from unilog_product_intelligence.retrieval.service import (
    ManufacturerJob,
    ManufacturerJobState,
)


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, product):
        self.calls += 1
        return product, ProductJob(
            job_id="phase4-job",
            product_id=product.product_id,
            state=JobState.CANDIDATES_ACCEPTED,
        )


class FakeDiscovery:
    def __init__(self, result: DiscoveryResult) -> None:
        self.result = result
        self.calls = 0

    def discover(self, **kwargs):
        self.calls += 1
        return self.result


class SearchCapability:
    def generate_with_tools(self, request, tools):
        raise AssertionError("not reached")


class FailingDiscovery:
    provider = SearchCapability()

    def discover(self, **kwargs):
        raise ProviderQuotaError()


class ProviderQuotaError(RuntimeError):
    status_code = 429
    provider_code = "too_many_requests"


class FakeManufacturer:
    def __init__(self, state: ManufacturerJobState = ManufacturerJobState.COMPLETED) -> None:
        self.state = state
        self.calls = 0
        self.inputs = []

    def process(self, product, source, profile, refresh=False):
        self.calls += 1
        self.inputs.append(product)
        job = ManufacturerJob(
            product_id=product.product_id,
            source_id=source.source_id,
            state=self.state,
            error="rejected" if self.state == ManufacturerJobState.REVIEW_REQUIRED else None,
        )
        if self.state != ManufacturerJobState.COMPLETED:
            return product, job
        truth = ProductTruthService()
        product = product.model_copy(deep=True)
        product.sources.append(
            Source(
                source_id=source.source_id,
                source_type=SourceType.MANUFACTURER_PAGE,
                authority=SourceAuthority.AUTHORITATIVE,
                uri=source.canonical_url,
            )
        )
        candidate = CandidateValue(
            candidate_id="manufacturer-candidate",
            raw_value="6",
            normalized_value="6",
            status=ValueStatus.CANDIDATE,
            source_ids=[source.source_id],
            assessment=AssessmentMetadata(
                source_authority=SourceAuthority.AUTHORITATIVE,
                evidence_available=True,
            ),
        )
        product = truth.add_classification(product, {})
        product = truth.add_attribute_candidate(
            product, "attribute-quantity", candidate, "Quantity"
        )
        return truth.attach_evidence(
            product,
            Evidence(
                evidence_id="manufacturer-evidence",
                source_id=source.source_id,
                product_id=product.product_id,
                attribute_id="attribute-quantity",
                candidate_id=candidate.candidate_id,
                quoted_text="Quantity: 6",
                evidence_type=EvidenceType.DIRECT_TEXT,
            ),
        ), job


class FakeEnrichment:
    def __init__(self) -> None:
        self.inputs = []

    def enrich(self, product, *args: object, **kwargs: object):
        self.inputs.append(product)
        return EnrichmentResult(
            product_id=product.product_id,
            status=EnrichmentStatus.ENRICHED,
            publication_state=PublicationState.READY,
            product_truth=product,
        )


class SearchProvider(LLMProvider):
    def __init__(self) -> None:
        self.tools = []
        self.calls = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request.task)
        return LLMResponse(output_text='{"candidates":[]}', model="test")

    def generate_with_tools(self, request: LLMRequest, tools):
        self.tools.append(tools)
        return LLMResponse(
            output_text=json.dumps(
                {
                    "candidates": [
                        {
                            "domain": "candidate.example",
                            "source": "search",
                            "reason": "Search result candidate",
                            "status": "candidate_manufacturer_source",
                        }
                    ],
                    "unresolved_reason": None,
                }
            ),
            model="test",
            tool_calls=1,
            search_call_count=1,
            search_queries=("Acme ABC123 official",),
        )


def _product():
    return ProductTruthService().create_from_raw_input(
        "product-1",
        {"Mfg_Part_Num": "ABC123", "Part_Desc": "6 pcs", "Part_Manuf": "Acme"},
        Source(
            source_id="input", source_type=SourceType.SUPPLIED_INPUT, authority=SourceAuthority.HIGH
        ),
    )


def _candidate_result() -> DiscoveryResult:
    return DiscoveryResult(
        candidates=[
            DomainCandidate(
                domain="acme.example",
                source="test",
                reason="verified test candidate",
                status=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
            )
        ]
    )


def _binding(product, discovery):
    source = SourceRecord(
        canonical_url="https://acme.example/ABC123",
        original_url="https://acme.example/ABC123",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="Acme",
        manufacturer_domain="acme.example",
        product_id=product.product_id,
    )
    return source, ManufacturerProfile(
        manufacturer_id="Acme", canonical_name="Acme", verified_domains=("acme.example",)
    )


def _pipeline(discovery, manufacturer, enrichment):
    return Phase65Pipeline(
        orchestrator=FakeOrchestrator(),
        discovery=FakeDiscovery(discovery),
        manufacturer=manufacturer,
        enrichment=enrichment,
        source_binding=_binding,
    )


def test_no_evidence_invokes_manufacturer_and_passes_evidence_to_phase6():
    manufacturer = FakeManufacturer()
    enrichment = FakeEnrichment()
    result = _pipeline(_candidate_result(), manufacturer, enrichment).run(_product())

    assert result.status == Phase65Status.ENRICHED
    assert manufacturer.calls == 1
    assert enrichment.inputs[0].evidence
    assert (
        evidence_references(enrichment.inputs[0])[0].source_id == result.manufacturer_job.source_id
    )
    assert result.product_truth.evidence[0].source_id == result.manufacturer_job.source_id


def test_verified_manufacturer_evidence_skips_discovery_and_retrieval():
    product = _product()
    manufacturer = FakeManufacturer()
    enrichment = FakeEnrichment()
    source = Source(
        source_id="verified-source",
        source_type=SourceType.MANUFACTURER_PAGE,
        authority=SourceAuthority.AUTHORITATIVE,
        uri="https://acme.example/ABC123",
    )
    product.sources.append(source)
    product.evidence.append(
        Evidence(
            evidence_id="verified-evidence",
            source_id=source.source_id,
            product_id=product.product_id,
            quoted_text="ABC123",
            evidence_type=EvidenceType.DIRECT_TEXT,
        )
    )
    discovery = FakeDiscovery(_candidate_result())
    pipeline = Phase65Pipeline(
        orchestrator=FakeOrchestrator(),
        discovery=discovery,
        manufacturer=manufacturer,
        enrichment=enrichment,
        source_binding=_binding,
    )

    result = pipeline.run(product)

    assert result.status == Phase65Status.ENRICHED
    assert discovery.calls == 0
    assert manufacturer.calls == 0
    assert enrichment.inputs[0].evidence


@pytest.mark.parametrize(
    ("discovery", "manufacturer", "blocker"),
    [
        (
            DiscoveryResult(unresolved_reason="no official domain"),
            FakeManufacturer(),
            "DOMAIN_UNRESOLVED",
        ),
        (
            _candidate_result(),
            FakeManufacturer(ManufacturerJobState.REVIEW_REQUIRED),
            "SOURCE_REJECTED",
        ),
    ],
)
def test_phase6_runs_and_reports_review_for_phase5_failures(discovery, manufacturer, blocker):
    enrichment = FakeEnrichment()
    result = _pipeline(discovery, manufacturer, enrichment).run(_product())

    assert result.status == Phase65Status.REVIEW_REQUIRED
    assert result.blocker == blocker
    assert enrichment.inputs


def test_deterministic_strategy_tried_when_registry_has_only_unverified_candidate():
    """When only a CANDIDATE domain is registered, DeterministicUrlStrategy is tried first.

    Under the new retrieval hierarchy, Gemini Search is NOT invoked until all
    deterministic paths are exhausted.  A CANDIDATE domain is enough to generate
    deterministic URL patterns — Gemini is a last resort, not a first resort.
    """
    provider = SearchProvider()
    agent = ManufacturerDiscoveryAgent(
        provider,
        DomainResolver(
            {
                "acme": ManufacturerProfile(
                    manufacturer_id="acme",
                    canonical_name="Acme",
                    candidate_domains=("registry.example",),
                )
            }
        ),
    )

    result = agent.discover("acme", "Acme", mpn="ABC123")

    # Deterministic path is taken — Gemini must NOT be called for a known candidate domain.
    assert result.search_requested is False
    assert result.search_tool_calls == 0
    # Candidate domain from registry must be in results
    assert any(c.domain == "registry.example" for c in result.candidates)
    # Deterministic URL strategy must be recorded
    assert "deterministic_url_patterns" in result.retrieval_strategies_attempted
    # No failure reason — deterministic path succeeded in generating candidates
    assert result.failure_reason is None


def test_input_evidence_never_becomes_manufacturer_evidence():
    product = _product()
    product.evidence.append(
        Evidence(
            evidence_id="input-evidence",
            source_id="input",
            product_id=product.product_id,
            quoted_text="6 pcs",
            evidence_type=EvidenceType.DIRECT_TEXT,
        )
    )

    assert evidence_references(product) == ()


def test_discovery_failure_preserves_sanitized_provider_detail():
    result = Phase65Pipeline(
        orchestrator=FakeOrchestrator(),
        discovery=FailingDiscovery(),
        manufacturer=FakeManufacturer(),
        enrichment=FakeEnrichment(),
        source_binding=_binding,
    ).run(_product())

    assert result.status == Phase65Status.REVIEW_REQUIRED
    assert result.blocker == "GEMINI_PROVIDER_429"
    assert result.phase5_error == ("discovery_failed:ProviderQuotaError:429:too_many_requests")
    assert result.discovery is not None
    assert result.discovery.unresolved_reason == result.phase5_error
    assert result.discovery.search_requested is True
    assert result.discovery.search_tool_calls == 0
