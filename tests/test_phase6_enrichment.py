"""Structural Phase 6 tests; no external model or web calls are made."""

import json

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.truth import (
    Evidence,
    EvidenceType,
    ProductClassification,
    Source,
    SourceAuthority,
    SourceType,
)
from unilog_product_intelligence.enrichment import (
    AttributePlanner,
    EnrichmentService,
    EvidenceGroundedEnrichmentAgent,
    ReferencePack,
    ValidationPipeline,
)
from unilog_product_intelligence.enrichment.models import ReferenceAvailability
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse


class FakeProvider(LLMProvider):
    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            output_text=json.dumps(
                {
                    "candidates": [
                        {
                            "attribute": "Material",
                            "value": "Stainless Steel",
                            "raw_value": "stainless steel",
                            "normalized_value": "Stainless Steel",
                            "evidence_id": "ev-1",
                            "evidence_text": "Material: stainless steel",
                            "status": "DIRECT",
                            "reason": "Directly stated in manufacturer technical document.",
                        }
                    ],
                    "unresolved_attributes": [],
                }
            ),
            model="gemini-3.5-flash-lite",
            input_tokens=10,
            output_tokens=8,
        )


def _product():
    source = Source(
        source_id="manufacturer-source",
        source_type=SourceType.MANUFACTURER_DOCUMENT,
        authority=SourceAuthority.AUTHORITATIVE,
        uri="https://manufacturer.example/spec.pdf",
    )
    truth = ProductTruthService().create_from_raw_input(
        "product-1",
        {"Mfg_Part_Num": "ABC-1", "Part_Desc": "Pipe fitting"},
        source,
    )
    truth = ProductTruthService().add_classification(
        truth,
        ProductClassification(class_name="Fittings", classpath=("Plumbing", "Fittings")),
    )
    truth.evidence.append(
        Evidence(
            evidence_id="ev-1",
            source_id=source.source_id,
            product_id=truth.product_id,
            quoted_text="Material: stainless steel",
            evidence_type=EvidenceType.DIRECT_TEXT,
        )
    )
    return truth


def test_planner_reports_reference_unavailable_without_fabricating_lov():
    product = _product()
    plans = AttributePlanner(
        reference_pack=ReferencePack(ReferenceAvailability.REFERENCE_UNAVAILABLE, {})
    ).plan(product)
    assert {plan.attribute_id for plan in plans} == {
        "fitting_type",
        "connection_type",
        "material",
        "size",
    }
    assert all(
        plan.reference_availability == ReferenceAvailability.REFERENCE_UNAVAILABLE for plan in plans
    )


def test_agent_candidate_is_evidence_backed_and_validated():
    product = _product()
    service = EnrichmentService(
        planner=AttributePlanner(
            reference_pack=ReferencePack(ReferenceAvailability.REFERENCE_UNAVAILABLE, {})
        ),
        agent=EvidenceGroundedEnrichmentAgent(FakeProvider()),
        validator=ValidationPipeline(),
    )
    result = service.enrich(product)
    assert result.candidates[0].evidence_ids == ("ev-1",)
    assert result.candidates[0].status.value in {"ENRICHED", "NORMALIZED"}
    assert result.product_truth.attribute("material").normalized_value == "Stainless Steel"
    assert result.metrics.agent_calls == 1


def test_untrusted_source_is_blocked():
    product = _product()
    product.sources[0].authority = SourceAuthority.LOW
    result = EnrichmentService(
        planner=AttributePlanner(), agent=EvidenceGroundedEnrichmentAgent(FakeProvider())
    ).enrich(product)
    assert result.publication_state.value == "BLOCKED"
