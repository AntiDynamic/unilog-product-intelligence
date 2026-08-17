"""Tests for Commerce Description Generation Layer (Phase 6)."""

from __future__ import annotations

import json
from pathlib import Path

from unilog_product_intelligence.agents.orchestration import JobState, ProductJob
from unilog_product_intelligence.application.phase65 import Phase65Result, Phase65Status
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.delivery.adapter import (
    DeliverySchemaContract,
    Phase65ResultDeliveryAdapter,
)
from unilog_product_intelligence.domain.models import Source, SourceAuthority, SourceType
from unilog_product_intelligence.domain.truth import (
    CandidateValue,
    Evidence,
    EvidenceType,
    ProductClassification,
    ProductTruth,
    ValueStatus,
)
from unilog_product_intelligence.enrichment.descriptions import (
    DescriptionAgent,
    DescriptionContext,
    DescriptionLimits,
    DescriptionService,
    DescriptionValidator,
    DeterministicDescriptionBuilder,
    GuidelineAssessmentStatus,
)
from unilog_product_intelligence.enrichment.models import ReferenceAvailability
from unilog_product_intelligence.enrichment.reference import ReferencePack
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse


class MockDescriptionProvider(LLMProvider):
    def __init__(self, response_dict: dict[str, object]) -> None:
        self.response_dict = response_dict

    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            output_text=json.dumps(self.response_dict),
            model="gemini-3.5-flash-lite",
            input_tokens=20,
            output_tokens=25,
        )


def _make_verified_product() -> ProductTruth:
    source = Source(
        source_id="mfg-src-1",
        source_type=SourceType.MANUFACTURER_DOCUMENT,
        authority=SourceAuthority.AUTHORITATIVE,
        uri="https://mfg.example.com/spec.pdf",
    )
    truth = ProductTruthService().create_from_raw_input(
        "prod-123",
        {
            "Mfg_Part_Num": "49-94-0013",
            "Part_Desc": "Cut-Off Wheel",
            "Unilog_Brand": "Milwaukee Tool",
            "Part_Manuf": "Milwaukee Tool",
        },
        source,
    )
    truth = ProductTruthService().add_classification(
        truth,
        ProductClassification(
            class_name="Cut-Off Wheels",
            classpath=("Abrasives", "Cut-Off Wheels"),
        ),
    )
    # Add authoritative evidence
    truth.evidence.append(
        Evidence(
            evidence_id="ev-1",
            source_id="mfg-src-1",
            product_id=truth.product_id,
            quoted_text=(
                "Wheel Diameter: 4-1/2 IN. Thickness: 0.045 IN. "
                "Arbor Size: 7/8 IN. Max RPM: 13300 RPM."
            ),
            evidence_type=EvidenceType.DIRECT_TEXT,
        )
    )

    # Add 3 verified attributes with evidence
    ts = ProductTruthService()
    truth = ts.add_attribute_candidate(
        truth,
        "wheel_diameter",
        CandidateValue(
            candidate_id="c-1",
            raw_value="4-1/2",
            normalized_value="4-1/2",
            uom="IN",
            evidence_ids=["ev-1"],
            status=ValueStatus.VERIFIED,
        ),
        canonical_name="Wheel Diameter",
    )
    truth = ts.add_attribute_candidate(
        truth,
        "thickness",
        CandidateValue(
            candidate_id="c-2",
            raw_value="0.045",
            normalized_value="0.045",
            uom="IN",
            evidence_ids=["ev-1"],
            status=ValueStatus.VERIFIED,
        ),
        canonical_name="Thickness",
    )
    truth = ts.add_attribute_candidate(
        truth,
        "arbor_size",
        CandidateValue(
            candidate_id="c-3",
            raw_value="7/8",
            normalized_value="7/8",
            uom="IN",
            evidence_ids=["ev-1"],
            status=ValueStatus.VERIFIED,
        ),
        canonical_name="Arbor Size",
    )

    for attr in truth.attributes:
        attr.status = ValueStatus.VERIFIED
        attr.evidence_ids = ["ev-1"]
        if attr.candidates:
            attr.normalized_value = attr.candidates[0].normalized_value
            attr.uom = attr.candidates[0].uom

    return truth


# ==============================================================================
# TEST A — BASIC DESCRIPTION BUILD
# ==============================================================================


def test_basic_description_build() -> None:
    """Assert all 5 commerce descriptions and feature bullets are generated."""
    product = _make_verified_product()
    ctx = DescriptionContext.from_product(product)
    builder = DeterministicDescriptionBuilder()
    descriptions = builder.build_all(ctx)

    assert descriptions.short is not None
    assert descriptions.long is not None
    assert descriptions.mobile is not None
    assert descriptions.invoice is not None
    assert descriptions.retail is not None
    assert len(descriptions.features) >= 3

    assert "Milwaukee Tool" in descriptions.short
    assert "49-94-0013" in descriptions.short
    assert "Cut-Off Wheel" in descriptions.short


# ==============================================================================
# TEST B — MPN PRESERVATION
# ==============================================================================


def test_mpn_preservation() -> None:
    """Assert every description requiring MPN contains 49-94-0013 and never another MPN."""
    product = _make_verified_product()
    ctx = DescriptionContext.from_product(product)
    builder = DeterministicDescriptionBuilder()
    descriptions = builder.build_all(ctx)

    assert "49-94-0013" in descriptions.short
    assert "49-94-0013" in descriptions.invoice
    assert "49-94-0013" in descriptions.mobile
    assert "49-94-0013" in descriptions.long

    # Validator confirms MPN preservation
    validator = DescriptionValidator()
    results = validator.validate(descriptions, ctx)
    mpn_errors = [r for r in results if r.validator == "mpn_preservation" and not r.passed]
    assert not mpn_errors


# ==============================================================================
# TEST C — NO HALLUCINATED ATTRIBUTE
# ==============================================================================


def test_no_hallucinated_attribute_repair() -> None:
    """When Gemini outputs forbidden claims or altered MPN, fallback repair protects truth."""
    product = _make_verified_product()
    ctx = DescriptionContext.from_product(product)

    # Provider attempts to hallucinate an altered MPN and forbidden superlatives
    bad_provider = MockDescriptionProvider({
        "short_desc": "Milwaukee Tool 99-99-9999 Super Cut-Off Wheel",
        "long_desc1": "The best in class cut-off wheel on earth.",
        "mobile_desc": "Milwaukee 99-99-9999 Wheel",
        "invoice_desc": "MILWAUKEE 99-99-9999 CUT-OFF WHEEL",
        "retail_desc": "An unmatched wheel with magic cutting power.",
        "features": ["Best in class performance"],
    })

    agent = DescriptionAgent(provider=bad_provider)
    descriptions, validations = agent.generate(ctx)

    # Validations caught the errors and repaired with deterministic baseline preserving real MPN
    assert descriptions.short is not None
    assert "49-94-0013" in descriptions.short
    assert "99-99-9999" not in descriptions.short
    assert "best in class" not in descriptions.long.lower()


# ==============================================================================
# TEST D — UOM FORMAT
# ==============================================================================


def test_uom_format_approved() -> None:
    """Descriptions use approved UOM representation from verified attributes."""
    product = _make_verified_product()
    ctx = DescriptionContext.from_product(product)
    builder = DeterministicDescriptionBuilder()
    descriptions = builder.build_all(ctx)

    assert "IN" in descriptions.short or "in" in descriptions.short.lower()
    assert "IN" in descriptions.long
    assert any("IN" in f for f in descriptions.features)


# ==============================================================================
# TEST E — CHARACTER LIMITS
# ==============================================================================


def test_character_limits_enforced() -> None:
    """Generated descriptions respect configured limits."""
    product = _make_verified_product()
    ctx = DescriptionContext.from_product(product)
    limits = DescriptionLimits(
        short_max=80,
        long_max=500,
        mobile_max=60,
        invoice_max=40,
        retail_max=300,
    )
    builder = DeterministicDescriptionBuilder(limits=limits)
    descriptions = builder.build_all(ctx)

    assert len(descriptions.short) <= 80
    assert len(descriptions.long) <= 500
    assert len(descriptions.mobile) <= 60
    assert len(descriptions.invoice) <= 40
    assert len(descriptions.retail) <= 300


# ==============================================================================
# TEST F — PRIORITY TRUNCATION
# ==============================================================================


def test_priority_truncation_preserves_mpn_and_product_type() -> None:
    """When short description exceeds limit, drop optional attributes first."""
    product = _make_verified_product()
    ctx = DescriptionContext.from_product(product)
    # Tight limit that forces attribute truncation
    tight_limits = DescriptionLimits(short_max=45)
    builder = DeterministicDescriptionBuilder(limits=tight_limits)
    short_desc = builder.build_short_desc(ctx)

    assert len(short_desc) <= 45
    assert "Milwaukee" in short_desc
    assert "49-94-0013" in short_desc
    assert "Cut-Off" in short_desc or "Wheel" in short_desc


# ==============================================================================
# TEST G — INVOICE STYLE
# ==============================================================================


def test_invoice_style_is_uppercase_and_transactional() -> None:
    """Invoice description is concise, transactional uppercase without promotional adjectives."""
    product = _make_verified_product()
    ctx = DescriptionContext.from_product(product)
    builder = DeterministicDescriptionBuilder()
    invoice = builder.build_invoice_desc(ctx)

    assert invoice.isupper()
    assert "49-94-0013" in invoice
    assert "MILWAUKEE" in invoice
    assert "PREMIUM" not in invoice
    assert "BEST" not in invoice


# ==============================================================================
# TEST H — MOBILE COMPACTNESS
# ==============================================================================


def test_mobile_compactness() -> None:
    """Mobile description is compact and product-identifying."""
    product = _make_verified_product()
    ctx = DescriptionContext.from_product(product)
    builder = DeterministicDescriptionBuilder()
    mobile = builder.build_mobile_desc(ctx)

    assert len(mobile) <= DescriptionLimits().mobile_max
    assert "Milwaukee" in mobile
    assert "49-94-0013" in mobile


# ==============================================================================
# TEST I — RETAIL EVIDENCE GROUNDING
# ==============================================================================


def test_retail_evidence_grounding() -> None:
    """Retail description is grounded in verified attributes and evidence snippets."""
    product = _make_verified_product()
    ctx = DescriptionContext.from_product(product)
    builder = DeterministicDescriptionBuilder()
    retail = builder.build_retail_desc(ctx)

    assert "Milwaukee Tool" in retail
    assert "49-94-0013" in retail
    assert "Cut-Off Wheel" in retail
    assert "unmatched" not in retail.lower()


# ==============================================================================
# TEST J — RAW MANUFACTURER COPY
# ==============================================================================


def test_raw_manufacturer_copy_preservation() -> None:
    """Features preserve authoritative manufacturer evidence bullet phrasing."""
    product = _make_verified_product()
    ctx = DescriptionContext.from_product(product)
    builder = DeterministicDescriptionBuilder()
    features = builder.build_features(ctx)

    assert len(features) >= 3
    assert any("Wheel Diameter" in f for f in features)
    assert any("Thickness" in f for f in features)


# ==============================================================================
# TEST K — MISSING GUIDELINES
# ==============================================================================


def test_missing_guidelines_reports_not_assessed() -> None:
    """When official content guideline workbook is absent, marks check as NOT_ASSESSED."""
    product = _make_verified_product()
    pack = ReferencePack(ReferenceAvailability.REFERENCE_UNAVAILABLE, {})
    ctx = DescriptionContext.from_product(product, reference_pack=pack)
    builder = DeterministicDescriptionBuilder()
    descriptions = builder.build_all(ctx)

    validator = DescriptionValidator()
    results = validator.validate(descriptions, ctx)

    guideline_res = next((r for r in results if r.validator == "guideline_availability"), None)
    assert guideline_res is not None
    assert guideline_res.guideline_status == GuidelineAssessmentStatus.NOT_ASSESSED


# ==============================================================================
# TEST L — DELIVERY ADAPTER INTEGRATION
# ==============================================================================


def test_delivery_adapter_maps_descriptions_to_252_columns() -> None:
    """Generated descriptions land in 252-column delivery fields."""
    product = _make_verified_product()
    service = DescriptionService()
    product, _ = service.generate_descriptions(product)

    root = Path(__file__).resolve().parent.parent
    schema_path = root / "docs" / "research" / "delivery-schema.json"
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    phase65_res = Phase65Result(
        product_truth=product,
        phase4_job=ProductJob(
            job_id="job-1", product_id=product.product_id, state=JobState.CANDIDATES_ACCEPTED
        ),
        status=Phase65Status.ENRICHED,
        resolved_manufacturer="Milwaukee Tool",
        resolved_brand="Milwaukee Tool",
    )

    record = adapter.to_record(phase65_res)
    assert len(record.as_row()) == 252

    values = record.values
    assert values["SHORT_DESC"] == product.descriptions.short
    assert values["LONG_DESC1"] == product.descriptions.long
    assert values["MOBILE_DESC"] == product.descriptions.mobile
    assert values["INVOICE_DESC"] == product.descriptions.invoice
    assert values["RETAIL_DESC"] == product.descriptions.retail

    # Check feature bullets mapping
    assert values["ITEM_FEATURES_1"] == product.descriptions.features[0]
    assert values["ITEM_FEATURES_2"] == product.descriptions.features[1]
    assert values["ITEM_FEATURES_3"] == product.descriptions.features[2]
