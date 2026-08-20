"""Tests for Task 6: Evidence-backed mapping of With, Standard/Approvals, and descriptions."""

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


def _make_test_product(pid: str = "prod-test-fields") -> ProductTruth:
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


def test_with_populated_only_when_evidence_exists() -> None:
    """Test that 'With' is populated when structured evidence exists and None when absent."""
    schema_path = (
        Path(__file__).resolve().parent.parent / "docs" / "research" / "delivery-schema.json"
    )
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    # 1. Without 'With' evidence -> None
    product_empty = _make_test_product("p-empty")
    res_empty = MagicMock(spec=Phase65Result)
    res_empty.product_truth = product_empty
    res_empty.manufacturer_job = None
    res_empty.status = Phase65Status.ENRICHED
    res_empty.resolved_manufacturer = "DeWalt"
    res_empty.resolved_brand = "DeWalt"
    res_empty.is_distributor_masked = False

    record_empty = adapter.to_record(res_empty)
    assert record_empty.values["With"] is None

    # 2. With structured 'Accessories Included' attribute -> Populated
    product_with = _make_test_product("p-with")
    product_with.attributes.append(
        AttributeRecord(
            attribute_id="attr-accessories",
            canonical_name="Accessories Included",
            normalized_value="Infeed/outfeed tables, extra set of knives",
            status=ValueStatus.VERIFIED,
            candidates=[
                CandidateValue(
                    candidate_id="cand-acc-1",
                    raw_value="Infeed/outfeed tables, extra set of knives",
                    normalized_value="Infeed/outfeed tables, extra set of knives",
                    status=ValueStatus.CANDIDATE,
                    source_ids=["src-1"],
                )
            ],
        )
    )

    res_with = MagicMock(spec=Phase65Result)
    res_with.product_truth = product_with
    res_with.manufacturer_job = None
    res_with.status = Phase65Status.ENRICHED
    res_with.resolved_manufacturer = "DeWalt"
    res_with.resolved_brand = "DeWalt"
    res_with.is_distributor_masked = False

    record_with = adapter.to_record(res_with)
    assert record_with.values["With"] == "Infeed/outfeed tables, extra set of knives"


def test_standard_approvals_populated_only_when_evidence_exists() -> None:
    """Test that 'Standard/Approvals' is populated when evidence exists and None when absent."""
    schema_path = (
        Path(__file__).resolve().parent.parent / "docs" / "research" / "delivery-schema.json"
    )
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    # 1. Without standard/approvals -> None
    product_empty = _make_test_product("p-no-std")
    res_empty = MagicMock(spec=Phase65Result)
    res_empty.product_truth = product_empty
    res_empty.manufacturer_job = None
    res_empty.status = Phase65Status.ENRICHED
    res_empty.resolved_manufacturer = "DeWalt"
    res_empty.resolved_brand = "DeWalt"
    res_empty.is_distributor_masked = False

    record_empty = adapter.to_record(res_empty)
    assert record_empty.values["Standard/Approvals"] is None

    # 2. With Certifications attribute -> Populated
    product_std = _make_test_product("p-std")
    product_std.attributes.append(
        AttributeRecord(
            attribute_id="attr-cert",
            canonical_name="Certifications",
            normalized_value="UL Listed, CSA Certified",
            status=ValueStatus.VERIFIED,
            candidates=[
                CandidateValue(
                    candidate_id="cand-cert-1",
                    raw_value="UL Listed, CSA Certified",
                    normalized_value="UL Listed, CSA Certified",
                    status=ValueStatus.CANDIDATE,
                    source_ids=["src-1"],
                )
            ],
        )
    )

    res_std = MagicMock(spec=Phase65Result)
    res_std.product_truth = product_std
    res_std.manufacturer_job = None
    res_std.status = Phase65Status.ENRICHED
    res_std.resolved_manufacturer = "DeWalt"
    res_std.resolved_brand = "DeWalt"
    res_std.is_distributor_masked = False

    record_std = adapter.to_record(res_std)
    assert record_std.values["Standard/Approvals"] == "UL Listed, CSA Certified"


def test_marketing_description_populated_from_descriptions() -> None:
    """Test that MARKETING_DESCRIPTION is populated from retail/marketing descriptions."""
    schema_path = (
        Path(__file__).resolve().parent.parent / "docs" / "research" / "delivery-schema.json"
    )
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    product = _make_test_product("p-mktg")
    product.descriptions = ProductDescriptions(
        short="DeWalt DW735X 13 in Planer",
        long="Technical long description for DeWalt DW735X.",
        mobile="DeWalt DW735X 13 in Planer",
        invoice="DEWALT DW735X PLANER",
        retail="High-performance benchtop thickness planer with three-knife cutter head.",
        marketing="The DeWalt DW735X provides superior finish and unmatched precision.",
        features=["15-Amp motor", "Two-speed gear box"],
    )

    res = MagicMock(spec=Phase65Result)
    res.product_truth = product
    res.manufacturer_job = None
    res.status = Phase65Status.ENRICHED
    res.resolved_manufacturer = "DeWalt"
    res.resolved_brand = "DeWalt"
    res.is_distributor_masked = False

    record = adapter.to_record(res)
    assert (
        record.values["MARKETING_DESCRIPTION"]
        == "The DeWalt DW735X provides superior finish and unmatched precision."
    )
