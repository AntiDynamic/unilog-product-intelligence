"""Single-product fixture E2E integration test for LIVE_GEMINI execution flow."""

from __future__ import annotations

import json

from unilog_product_intelligence.agents.orchestration import ProductOrchestrator
from unilog_product_intelligence.application.phase65 import Phase65Pipeline
from unilog_product_intelligence.delivery import (
    DeliverySchemaContract,
    Phase65ResultDeliveryAdapter,
)
from unilog_product_intelligence.domain.truth import ProductTruth, RawInputField
from unilog_product_intelligence.enrichment.agent import EvidenceGroundedEnrichmentAgent
from unilog_product_intelligence.enrichment.descriptions import DescriptionAgent, DescriptionService
from unilog_product_intelligence.enrichment.planner import AttributePlanner
from unilog_product_intelligence.enrichment.service import EnrichmentService
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.retrieval.agents import DiscoveryResult, ManufacturerDiscoveryAgent
from unilog_product_intelligence.retrieval.core import (
    CacheStatus,
    DomainCandidate,
    DomainResolver,
    FetchResult,
    ManufacturerProfile,
    RetrievalStatus,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourceRecord,
)
from unilog_product_intelligence.retrieval.service import ManufacturerIntelligenceService

FIXTURE_HTML = b"""<!DOCTYPE html>
<html>
<head>
    <title>Diablo DCB518ASTS06G Sanding Belt 5 in x 18 in 60 Grit</title>
    <meta property="og:title" content="Diablo DCB518ASTS06G Sanding Belt" />
    <meta property="og:description"
          content="Premium Diablo sanding belt for heavy stock removal on wood and metal." />
    <meta property="og:image" content="https://diablotools.com/images/products/DCB518ASTS06G.jpg" />
    <script type="application/ld+json">
    {
      "@context": "https://schema.org/",
      "@type": "Product",
      "name": "Diablo DCB518ASTS06G Sanding Belt",
      "mpn": "DCB518ASTS06G",
      "brand": {
        "@type": "Brand",
        "name": "Diablo"
      },
      "manufacturer": {
        "@type": "Organization",
        "name": "Freud Inc"
      },
      "image": "https://diablotools.com/images/products/DCB518ASTS06G.jpg"
    }
    </script>
</head>
<body>
    <h1>Diablo DCB518ASTS06G Sanding Belt</h1>
    <p class="description">Premium Diablo sanding belt for heavy duty sanding.</p>
    
    <h2>Specifications</h2>
    <table class="specs">
        <tr><td>Diameter</td><td>5 in</td></tr>
        <tr><td>Thickness</td><td>.045 in</td></tr>
        <tr><td>Grit</td><td>60 Grit</td></tr>
        <tr><td>Material</td><td>Zirconia Alumina</td></tr>
        <tr><td>Backing Weight</td><td>X-Weight Cloth</td></tr>
    </table>

    <h2>Features</h2>
    <ul>
        <li>Heavy-duty cloth backing for maximum durability</li>
        <li>Clog-shield technology reduces loading</li>
    </ul>

    <h2>Documents</h2>
    <a href="https://diablotools.com/docs/DCB518ASTS06G_spec.pdf">Technical Data Sheet (PDF)</a>
</body>
</html>
"""


class RecordingMockGeminiProvider(LLMProvider):
    """Mock Gemini provider that records received prompts and returns valid envelope JSONs."""

    def __init__(self) -> None:
        self.recorded_requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.recorded_requests.append(request)

        if request.task == "product_understanding":
            output = json.dumps({
                "product_type": "Sanding Belt",
                "product_family": "Abrasives",
                "semantic_features": ["60 Grit", "Zirconia Alumina"],
                "evidence": [],
                "uncertain_items": []
            })
        elif request.task == "classification":
            output = json.dumps({
                "candidates": [
                    {
                        "department": "Abrasives",
                        "class_name": "Sanding Belts & Discs",
                        "fine": "Sanding Belts",
                        "classpath": ["Abrasives", "Sanding Belts & Discs", "Sanding Belts"]
                    }
                ],
                "selected_candidate": 0,
                "unresolved_reason": None
            })
        elif request.task == "attribute_extraction":
            output = json.dumps({
                "attributes": [],
                "missing_attributes": ["Diameter", "Thickness", "Grit"]
            })
        elif request.task == "evidence_grounded_enrichment":
            # Extract evidence IDs from prompt lines
            evidence_ids = []
            for line in request.input_text.splitlines():
                if "evidence_id=" in line:
                    ev_id = line.split("evidence_id=")[1].split()[0]
                    evidence_ids.append(ev_id)
            
            ev_id_1 = evidence_ids[0] if evidence_ids else "evidence-mock-1"
            ev_id_2 = evidence_ids[1] if len(evidence_ids) > 1 else ev_id_1

            output = json.dumps({
                "candidates": [
                    {
                        "attribute": "Diameter",
                        "value": "5",
                        "raw_value": "5 in",
                        "normalized_value": "5",
                        "uom": "in",
                        "evidence_id": ev_id_1,
                        "evidence_text": "Diameter: 5 in",
                        "status": "enriched",
                        "reason": "Direct spec table value"
                    },
                    {
                        "attribute": "Thickness",
                        "value": ".045",
                        "raw_value": ".045 in",
                        "normalized_value": ".045",
                        "uom": "in",
                        "evidence_id": ev_id_2,
                        "evidence_text": "Thickness: .045 in",
                        "status": "enriched",
                        "reason": "Direct spec table value"
                    }
                ]
            })
        elif request.task == "commerce_description_composition":
            output = json.dumps({
                "short_desc": "Diablo DCB518ASTS06G Sanding Belt 5 in 60 Grit",
                "long_desc1": (
                    "The Diablo DCB518ASTS06G sanding belt provides heavy duty "
                    "sanding performance with 5 in diameter and .045 in thickness."
                ),
                "mobile_desc": "Diablo DCB518ASTS06G Sanding Belt 5 in",
                "invoice_desc": "DIABLO DCB518ASTS06G SANDING BELT",
                "retail_desc": "Heavy-duty Diablo sanding belt for superior stock removal.",
                "features": [
                    "Heavy-duty cloth backing for maximum durability",
                    "Clog-shield technology reduces loading",
                ],
            })
        else:
            output = json.dumps({})

        return LLMResponse(
            output_text=output,
            model="mock-gemini-3.5-flash-lite",
            input_tokens=150,
            output_tokens=100,
            latency_ms=45,
            cached_tokens=0,
        )

    def generate_with_tools(self, request: LLMRequest) -> LLMResponse:
        return self.generate(request)


class CustomMockFetcher(SourceFetcher):
    """Fetcher that returns FIXTURE_HTML for diablotools.com URLs."""

    def fetch(self, record: SourceRecord, refresh: bool = False) -> FetchResult:
        source_copy = record.model_copy(
            update={
                "fetched_at": record.fetched_at,
                "retrieval_status": RetrievalStatus.SUCCESS,
            }
        )
        return FetchResult(
            source=source_copy,
            body=FIXTURE_HTML,
            cache_status=CacheStatus.MISS,
        )


def test_live_gemini_single_product_e2e_flow() -> None:
    # 1. Setup mock provider and services
    provider = RecordingMockGeminiProvider()
    orchestrator = ProductOrchestrator(provider)
    fetcher = CustomMockFetcher()
    mfg_service = ManufacturerIntelligenceService(fetcher=fetcher)

    agent = EvidenceGroundedEnrichmentAgent(provider=provider)
    enrichment_service = EnrichmentService(
        planner=AttributePlanner(),
        agent=agent,
        description_service=DescriptionService(agent=DescriptionAgent(provider=provider)),
    )

    class MockDiscoveryAgent(ManufacturerDiscoveryAgent):
        def __init__(self, p: LLMProvider) -> None:
            super().__init__(p, DomainResolver())

        def discover(
            self,
            manufacturer_id: str,
            manufacturer_name: str,
            mpn: str | None = None,
            family: str | None = None,
            description: str | None = None,
            brand: str | None = None,
        ) -> DiscoveryResult:
            return DiscoveryResult(
                candidates=[
                    DomainCandidate(
                        domain="diablotools.com",
                        source="catalog",
                        reason="verified_domain",
                        status=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                    )
                ],
                search_requested=False,
            )

    pipeline = Phase65Pipeline(
        orchestrator=orchestrator,
        discovery=MockDiscoveryAgent(provider),
        manufacturer=mfg_service,
        enrichment=enrichment_service,
        source_binding=lambda prod, disc: (
            SourceRecord(
                canonical_url="https://diablotools.com/products/DCB518ASTS06G",
                original_url="https://diablotools.com/products/DCB518ASTS06G",
                source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
                decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                manufacturer_id="Freud Inc (2435)",
                manufacturer_domain="diablotools.com",
            ),
            ManufacturerProfile(
                manufacturer_id="m-freud",
                canonical_name="Freud Inc (2435)",
                verified_domains=("diablotools.com",),
            ),
        ),
    )

    # 2. Input Product Truth
    product = ProductTruth(
        product_id="test-dcb518",
        raw_inputs=[
            RawInputField(
                field_name="SKU - MY_PART_NUMBER", raw_value="DCB518ASTS06G", source_id="input-1"
            ),
            RawInputField(
                field_name="Mfg_Part_Num", raw_value="DCB518ASTS06G", source_id="input-1"
            ),
            RawInputField(
                field_name="Part_Manuf", raw_value="Freud Inc (2435)", source_id="input-1"
            ),
            RawInputField(field_name="Unilog_Brand", raw_value="Diablo", source_id="input-1"),
            RawInputField(
                field_name="Part_Desc", raw_value="DCB518ASTS06G Sanding Belt", source_id="input-1"
            ),
        ],
    )

    # 3. Execute Pipeline
    result = pipeline.run(product)

    # 4. Verify Phase65Result and State Integrity
    assert result.status.value in {"ENRICHED", "REVIEW_REQUIRED"}
    assert result.manufacturer_job is not None
    assert result.manufacturer_job.source_is_product_verified is True
    assert result.manufacturer_job.verified_source_context is not None

    source_ctx = result.manufacturer_job.verified_source_context
    assert source_ctx.canonical_product_url == "https://diablotools.com/products/DCB518ASTS06G"
    assert "DCB518ASTS06G" in source_ctx.page_title

    # 5. Assert Prompt Inspection (PART 19 Requirement)
    enrichment_requests = [
        req for req in provider.recorded_requests if req.task == "evidence_grounded_enrichment"
    ]
    assert len(enrichment_requests) > 0, "No enrichment prompt was sent to Gemini!"
    prompt_text = enrichment_requests[0].input_text

    # Assert that prompt contains MPN and at least two actual manufacturer spec texts
    assert "DCB518ASTS06G" in prompt_text, "Prompt missing MPN 'DCB518ASTS06G'!"
    assert "Diameter" in prompt_text, "Prompt missing spec 'Diameter' from HTML!"
    assert "Thickness" in prompt_text, "Prompt missing spec 'Thickness' from HTML!"

    # 6. Assert Candidates Accepted and Validated
    truth = result.product_truth
    diam_attr = truth.attribute("attribute-diameter")
    assert diam_attr is not None
    assert diam_attr.normalized_value == "5" or diam_attr.raw_value == "5 in"

    # 7. Verify Delivery CSV Generation
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    schema_path = root / "docs" / "research" / "delivery-schema.json"
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)
    delivery_record = adapter.to_record(result)
    row_dict = delivery_record.values

    is_mpn_valid = (
        row_dict.get("MANUFACTURER_PART_NUMBER") == "DCB518ASTS06G"
        or row_dict.get("Mfg_Part_Num") == "DCB518ASTS06G"
    )
    assert is_mpn_valid
    assert "Freud" in str(row_dict.get("MANUFACTURER_NAME"))
    assert row_dict.get("BRAND_NAME") == "Diablo" or row_dict.get("Unilog_Brand") == "Diablo"
    assert bool(row_dict.get("Product Image")), "Product Image must be populated!"
    assert row_dict.get("Product Image") == "https://diablotools.com/images/products/DCB518ASTS06G.jpg"
