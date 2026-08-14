from unilog_product_intelligence.agents.orchestration import JobState, ProductOrchestrator
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.truth import Source, SourceAuthority, SourceType
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.tools import ApplicationTools


class FakeProvider(LLMProvider):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request.task)
        outputs = {
            "product_understanding": '{"product_type":"fitting","product_family":null,"semantic_features":[],"evidence":[],"uncertain_items":[]}',  # noqa: E501
            "classification": '{"candidates":[],"selected_candidate":null,"unresolved_reason":"taxonomy unavailable"}',  # noqa: E501
            "attribute_extraction": '{"attributes":[{"attribute":"quantity","raw_value":"6 pcs","normalized_candidate":"6","unit":"pcs","evidence":{"field_name":"Part_Desc","quoted_text":"6 pcs","kind":"directly_present"},"status":"directly_present"}],"missing_attributes":["material"]}',  # noqa: E501
        }
        return LLMResponse(output_text=outputs[request.task], model="test-model")


def test_orchestrator_maps_only_evidence_supported_candidates() -> None:
    provider = FakeProvider()
    source = Source(
        source_id="input", source_type=SourceType.SUPPLIED_INPUT, authority=SourceAuthority.HIGH
    )
    product = ProductTruthService().create_from_raw_input(
        "row-1", {"Part_Desc": "1/2 x 18 in, 6 pcs"}, source
    )
    product, job = ProductOrchestrator(provider).run(product)

    assert job.state == JobState.CANDIDATES_ACCEPTED
    assert provider.calls == ["product_understanding", "classification", "attribute_extraction"]
    assert product.attribute("attribute-quantity").candidates[0].raw_value == "6 pcs"
    assert product.attribute("attribute-quantity").candidates[0].status.value == "candidate"
    assert product.attribute("attribute-quantity").candidates[0].evidence_ids


def test_unavailable_application_tools_are_explicit() -> None:
    result = ApplicationTools().resolve_manufacturer("unknown")
    assert result.status == "reference_data_unavailable"
