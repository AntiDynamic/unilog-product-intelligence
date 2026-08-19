"""Tests for Task 5: Source-grounded feature extraction and delivery column mapping."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from unilog_product_intelligence.application.phase65 import (
    Phase65Result,
    Phase65Status,
)
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.delivery.adapter import (
    DeliverySchemaContract,
    Phase65ResultDeliveryAdapter,
)
from unilog_product_intelligence.domain.truth import (
    AttributeRecord,
    CandidateValue,
    ProductDescriptions,
    ProductTruth,
    Source,
    SourceAuthority,
    SourceType,
    ValueStatus,
)
from unilog_product_intelligence.enrichment.descriptions import (
    DescriptionContext,
    DeterministicDescriptionBuilder,
    _clean_feature_text,
)


def _make_test_product(pid: str = "prod-test-feat") -> ProductTruth:
    service = ProductTruthService()
    source = Source(
        source_id="input-1",
        source_type=SourceType.SUPPLIED_INPUT,
        authority=SourceAuthority.LOW,
    )
    return service.create_from_raw_input(
        pid,
        {
            "Mfg_Part_Num": "DW735X",
            "Part_Manuf": "DeWalt",
            "Part_Desc": "DeWalt 13 in Two-Speed Thickness Planer",
        },
        source,
    )


def test_clean_feature_text_strips_markers_and_filters_boilerplate() -> None:
    """Test leading bullets, numbering, and headers are cleanly stripped or filtered."""
    # Leading markers stripped
    assert _clean_feature_text("• Powerful 15-Amp motor") == "Powerful 15-Amp motor"
    assert _clean_feature_text("- Two-speed gear box") == "Two-speed gear box"
    assert _clean_feature_text("1. Three-knife cutter-head") == "Three-knife cutter-head"
    assert _clean_feature_text("* 13-inch capacity") == "13-inch capacity"
    assert _clean_feature_text("1) Fan-assisted chip ejection") == "Fan-assisted chip ejection"

    # Generic headers filtered out
    assert _clean_feature_text("Features:") is None
    assert _clean_feature_text("Key Features") is None
    assert _clean_feature_text("Specifications") is None
    assert _clean_feature_text("Overview") is None
    assert _clean_feature_text("http://example.com/spec") is None
    assert _clean_feature_text("None") is None
    assert _clean_feature_text("N/A") is None


def test_build_features_from_evidence_and_verified_attributes() -> None:
    """Test features constructed from snippets and verified attributes without duplicates."""
    builder = DeterministicDescriptionBuilder()
    product = _make_test_product()

    attr_rec = AttributeRecord(
        attribute_id="attr-voltage",
        canonical_name="Voltage",
        normalized_value="120",
        uom="V",
        status=ValueStatus.VERIFIED,
        candidates=[
            CandidateValue(
                candidate_id="cand-1",
                raw_value="120 V",
                normalized_value="120",
                uom="V",
                status=ValueStatus.CANDIDATE,
                source_ids=["src-1"],
                evidence_ids=["ev-1"],
            )
        ],
    )

    dup_text = "• Powerful 15-amp, 20,000 RPM motor handles larger cuts in wider materials"
    evidence_snippets = (
        "• Powerful 15-amp, 20,000 RPM motor handles larger cuts in wider materials",
        "• Two-speed gear box allows users to change feed speed to optimizing cuts per inch",
        "• Three-knife cutter head delivers 30 percent longer knife life",
        "Features:",  # should be ignored
        dup_text,  # duplicate -> ignored
    )

    ctx = DescriptionContext(
        product_id=product.product_id,
        brand="DeWalt",
        manufacturer="DeWalt",
        mpn="DW735X",
        product_name="13 in Two-Speed Thickness Planer",
        series=None,
        trade_name=None,
        classpath=("Tools", "Power Tools", "Planers"),
        category="Planers",
        verified_attributes=(attr_rec,),
        evidence_snippets=evidence_snippets,
        approved_uoms=frozenset(["V", "RPM", "in", "amp"]),
    )

    features = builder.build_features(ctx)

    assert len(features) >= 4
    # All bullets stripped of '• '
    assert features[0] == "Powerful 15-amp, 20,000 RPM motor handles larger cuts in wider materials"
    exp_f1 = "Two-speed gear box allows users to change feed speed to optimizing cuts per inch"
    assert features[1] == exp_f1
    assert features[2] == "Three-knife cutter head delivers 30 percent longer knife life"
    assert "Voltage: 120 V" in features
    # No generic header in bullets
    assert "Features:" not in features
    # No duplicate bullets
    assert len(features) == len(set(f.casefold() for f in features))


def test_delivery_adapter_populates_item_features_up_to_20() -> None:
    """Test that Phase65ResultDeliveryAdapter populates ITEM_FEATURES_1..20 correctly."""
    product = _make_test_product()
    sample_features = [
        f"Feature bullet number {i}" for i in range(1, 8)
    ]
    product.descriptions = ProductDescriptions(
        short="DeWalt DW735X 13 in Planer",
        long="Technical long description for DeWalt DW735X.",
        mobile="DeWalt DW735X 13 in Planer",
        invoice="DEWALT DW735X PLANER",
        retail="Retail customer-facing description.",
        features=sample_features,
    )

    phase65_res = MagicMock(spec=Phase65Result)
    phase65_res.product_truth = product
    phase65_res.manufacturer_job = None
    phase65_res.status = Phase65Status.ENRICHED
    phase65_res.resolved_manufacturer = "DeWalt"
    phase65_res.resolved_brand = "DeWalt"
    phase65_res.is_distributor_masked = False

    schema_path = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "research"
        / "delivery-schema.json"
    )
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    record = adapter.to_record(phase65_res)
    values = record.values

    # Check that ITEM_FEATURES_1 to 7 are populated
    for i in range(1, 8):
        assert values[f"ITEM_FEATURES_{i}"] == f"Feature bullet number {i}"

    # Check that ITEM_FEATURES_8 to 20 are None
    for i in range(8, 21):
        assert values[f"ITEM_FEATURES_{i}"] is None
