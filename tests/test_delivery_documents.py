"""Tests for Task 4: Verified Document and Ref URL propagation and ranking in delivery adapter."""

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
    _extract_source_urls,
    _rank_document_url,
)
from unilog_product_intelligence.domain.source_context import (
    VerifiedProductSourceContext,
)
from unilog_product_intelligence.domain.truth import (
    AssetType,
    DigitalAsset,
    ProductTruth,
    Source,
    SourceAuthority,
    SourceType,
)
from unilog_product_intelligence.retrieval.service import (
    ManufacturerJob,
    ManufacturerJobState,
)


def _make_test_product(pid: str = "prod-test-doc") -> ProductTruth:
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


def test_document_urls_ranked_by_priority() -> None:
    """Test priority ranking: manual > spec > tech doc > warranty > other."""
    manual_url = "https://dewalt.com/documents/DW735X_instruction_manual.pdf"
    spec_url = "https://dewalt.com/specs/DW735X_cutsheet.pdf"
    tech_url = "https://dewalt.com/tech/DW735X_wiring_diagram.pdf"
    warranty_url = "https://dewalt.com/legal/dewalt_3yr_warranty.pdf"
    other_url = "https://dewalt.com/downloads/general_sheet.pdf"
    misc_page = "https://dewalt.com/accessories/blades"

    assert _rank_document_url(manual_url) == 1
    assert _rank_document_url(spec_url) == 2
    assert _rank_document_url(tech_url) == 3
    assert _rank_document_url(warranty_url) == 4
    assert _rank_document_url(other_url) == 5
    assert _rank_document_url(misc_page) == 6


def test_ref_urls_populated_and_ranked_from_verified_source_context() -> None:
    """Test document_urls in verified_source_context mapped into Ref URL 1..5."""
    product = _make_test_product()
    canonical_url = "https://dewalt.com/products/DW735X"
    doc_urls = [
        "https://dewalt.com/legal/warranty_info.pdf",
        "https://dewalt.com/specs/DW735X_specification_sheet.pdf",
        "https://dewalt.com/manuals/DW735X_user_manual.pdf",
        "https://dewalt.com/tech/DW735X_service_bulletin.pdf",
    ]

    source_ctx = VerifiedProductSourceContext(
        product_id=product.product_id,
        canonical_product_url=canonical_url,
        source_id="src-dewalt",
        source_authority="AUTHORITATIVE",
        source_type="MANUFACTURER_PAGE",
        document_urls=doc_urls,
    )

    mfg_job = ManufacturerJob(
        job_id="job-mfg",
        product_id=product.product_id,
        state=ManufacturerJobState.COMPLETED,
        verified_source_context=source_ctx,
    )

    phase65_res = MagicMock(spec=Phase65Result)
    phase65_res.product_truth = product
    phase65_res.manufacturer_job = mfg_job
    phase65_res.status = Phase65Status.ENRICHED
    phase65_res.resolved_manufacturer = "DeWalt"
    phase65_res.resolved_brand = "DeWalt"
    phase65_res.is_distributor_masked = False

    schema_path = (
        Path(__file__).resolve().parent.parent / "docs" / "research" / "delivery-schema.json"
    )
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    record = adapter.to_record(phase65_res)
    values = record.values

    # MFR URL is primary product page
    assert values["MFR URL"] == canonical_url

    # Ref URL 1: User Manual (rank 1)
    assert values["Ref URL 1"] == "https://dewalt.com/manuals/DW735X_user_manual.pdf"
    # Ref URL 2: Specification Sheet (rank 2)
    assert values["Ref URL 2"] == "https://dewalt.com/specs/DW735X_specification_sheet.pdf"
    # Ref URL 3: Technical Service Bulletin (rank 3)
    assert values["Ref URL 3"] == "https://dewalt.com/tech/DW735X_service_bulletin.pdf"
    # Ref URL 4: Warranty (rank 4)
    assert values["Ref URL 4"] == "https://dewalt.com/legal/warranty_info.pdf"
    # Ref URL 5: None (only 4 documents supplied)
    assert values["Ref URL 5"] is None


def test_ref_urls_deduplication_and_mfr_url_exclusion() -> None:
    """Test canonical MFR URL is excluded from Ref URLs and duplicates are merged."""
    product = _make_test_product()
    canonical_url = "https://dewalt.com/products/DW735X"
    doc_urls = [
        canonical_url,  # exact duplicate of MFR URL -> should be excluded
        "https://dewalt.com/manuals/DW735X_Manual.pdf",
        "https://DEWALT.com/manuals/DW735X_MANUAL.pdf",  # case duplicate -> should be deduped
        "https://dewalt.com/specs/DW735X_spec.pdf",
    ]

    source_ctx = VerifiedProductSourceContext(
        product_id=product.product_id,
        canonical_product_url=canonical_url,
        source_id="src-dewalt",
        source_authority="AUTHORITATIVE",
        source_type="MANUFACTURER_PAGE",
        document_urls=doc_urls,
    )

    mfg_job = ManufacturerJob(
        job_id="job-mfg-2",
        product_id=product.product_id,
        state=ManufacturerJobState.COMPLETED,
        verified_source_context=source_ctx,
    )

    mfr_url, ref_urls = _extract_source_urls(MagicMock(manufacturer_job=mfg_job), product)

    assert mfr_url == canonical_url
    assert len(ref_urls) == 2
    assert ref_urls[0] == "https://dewalt.com/manuals/DW735X_Manual.pdf"
    assert ref_urls[1] == "https://dewalt.com/specs/DW735X_spec.pdf"


def test_digital_assets_documents_propagate_to_ref_urls() -> None:
    """Test that document DigitalAssets on ProductTruth are also propagated."""
    product = _make_test_product()
    product.digital_assets.extend(
        [
            DigitalAsset(
                asset_id="asset-1",
                source_id="src-asset",
                asset_type=AssetType.DOCUMENT,
                uri="https://manufacturer.com/downloads/manual.pdf",
            ),
            DigitalAsset(
                asset_id="asset-2",
                source_id="src-asset",
                asset_type=AssetType.BROCHURE,
                uri="https://manufacturer.com/downloads/spec_sheet.pdf",
            ),
        ]
    )

    mfr_url, ref_urls = _extract_source_urls(MagicMock(manufacturer_job=None), product)

    assert "https://manufacturer.com/downloads/manual.pdf" in ref_urls
    assert "https://manufacturer.com/downloads/spec_sheet.pdf" in ref_urls
    assert ref_urls[0] == "https://manufacturer.com/downloads/manual.pdf"  # ranked 1
    assert ref_urls[1] == "https://manufacturer.com/downloads/spec_sheet.pdf"  # ranked 2
