"""Tests for BrandManufacturerResolver and Phase65ResultDeliveryAdapter."""

from __future__ import annotations

from pathlib import Path

from unilog_product_intelligence.agents.orchestration import JobState, ProductJob
from unilog_product_intelligence.application.brand_resolver import (
    BrandManufacturerResolver,
    ResolvedIdentity,
)
from unilog_product_intelligence.application.phase65 import Phase65Result, Phase65Status
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.delivery.adapter import (
    DeliverySchemaContract,
    Phase65ResultDeliveryAdapter,
    UniHackDeliveryRecord,
)
from unilog_product_intelligence.domain.truth import (
    CandidateValue,
    LifecycleState,
    ProductClassification,
    ProductDescriptions,
    Source,
    SourceAuthority,
    SourceType,
    ValueStatus,
)
from unilog_product_intelligence.enrichment.models import (
    EnrichmentResult,
    EnrichmentStatus,
    PublicationState,
)
from unilog_product_intelligence.retrieval.service import (
    ManufacturerJob,
    ManufacturerJobState,
)

# ── BrandManufacturerResolver Tests ──────────────────────────────────────────


def test_brand_resolver_detects_jamin_distributor() -> None:
    resolver = BrandManufacturerResolver()
    result = resolver.resolve(
        "Jam Industrial Supply LLC (JAMIN)",
        "3M 775L Stikit Film Disc 5 in 150+ 00645",
    )
    assert isinstance(result, ResolvedIdentity)
    assert result.is_distributor is True
    assert result.manufacturer == "3m"
    assert result.brand == "3M"
    assert result.resolution_method == "distributor_map"


def test_brand_resolver_detects_mirus_distributor() -> None:
    resolver = BrandManufacturerResolver()
    result = resolver.resolve(
        "Mirka Abrasives Inc (MIRUS)",
        "5B-332-080 HIOLIT 5\" P80",
    )
    assert result.is_distributor is True
    assert result.manufacturer == "mirka abrasives"
    assert result.brand == "Mirka"


def test_brand_resolver_falls_back_to_description_for_unmapped_distributor() -> None:
    resolver = BrandManufacturerResolver()
    result = resolver.resolve(
        "Appliance Dealers Cooperative (APPDE)",
        "Rheem Performance Platinum 50 Gal Water Heater",
    )
    assert result.is_distributor is True
    assert result.manufacturer == "rheem"
    assert result.brand == "Rheem"
    assert result.resolution_method == "desc_brand_token"


def test_brand_resolver_preserves_real_manufacturer() -> None:
    resolver = BrandManufacturerResolver()
    result = resolver.resolve(
        "Freud Inc (2435)",
        "DCB518ASTS06G Diablo 1/2\"x18\" - Sanding Belt 6pc",
    )
    assert result.is_distributor is False
    assert result.manufacturer == "Freud Inc"
    assert result.resolution_method == "raw_manuf"


# ── Phase65ResultDeliveryAdapter Tests ─────────────────────────────────────────


def test_delivery_adapter_synthesizes_252_columns() -> None:
    root = Path(__file__).resolve().parent.parent
    schema_path = root / "docs" / "research" / "delivery-schema.json"
    contract = DeliverySchemaContract.from_json(schema_path)
    assert contract.available is True
    assert len(contract.headers) == 252

    adapter = Phase65ResultDeliveryAdapter(contract)
    truth_service = ProductTruthService()

    raw_dict = {
        "Mfg_Part_Num": "DCB518ASTS06G",
        "Part_Desc": "DCB518ASTS06G Diablo 1/2\"x18\" - Sanding Belt 6pc",
        "E1_Brand": "-- Unbranded --",
        "Unilog_Brand": "-- No Unilog Brand --",
        "DIB_Brand": "-- No DIB Brand --",
        "Part_Manuf": "Freud Inc (2435)",
    }
    source = Source(
        source_id="test-source-1",
        source_type=SourceType.SUPPLIED_INPUT,
        authority=SourceAuthority.HIGH,
    )
    product = truth_service.create_from_raw_input("prod-1", raw_dict, source)

    # Attach classification
    product = product.model_copy(
        update={
            "lifecycle_state": LifecycleState.CLASSIFIED,
            "classification": ProductClassification(
                department="Tools",
                class_name="Industrial",
                fine="General",
                classpath=("Tools", "Industrial", "General"),
            ),
            "descriptions": ProductDescriptions(
                short="Diablo Sanding Belt 6-Pack",
                long="Diablo premium sanding belts for aggressive stock removal.",
                features=["Fast material removal", "Stearate anti-clog coating"],
            ),
        }
    )

    # Add attribute candidates
    product = truth_service.add_attribute_candidate(
        product,
        "attribute-brand",
        CandidateValue(
            candidate_id="cand-1",
            raw_value="Diablo",
            normalized_value="Diablo",
            status=ValueStatus.CANDIDATE,
            source_ids=["test-source-1"],
        ),
        "Brand",
    )

    mfg_job = ManufacturerJob(
        product_id="prod-1",
        state=ManufacturerJobState.COMPLETED,
        url_context_urls=("https://diablotools.com/products/DCB518ASTS06G",),
    )

    phase65_res = Phase65Result(
        product_truth=product,
        phase4_job=ProductJob(
            job_id="job-1", product_id="prod-1", state=JobState.CANDIDATES_ACCEPTED
        ),
        manufacturer_job=mfg_job,
        enrichment=EnrichmentResult(
            product_id="prod-1",
            product_truth=product,
            status=EnrichmentStatus.ENRICHED,
            publication_state=PublicationState.READY,
        ),
        status=Phase65Status.ENRICHED,
        resolved_manufacturer="Freud Inc",
        resolved_brand="Diablo",
        is_distributor_masked=False,
    )

    record = adapter.to_record(phase65_res)
    assert isinstance(record, UniHackDeliveryRecord)

    row = record.as_row()
    assert len(row) == 252

    # Verify key columns
    values = record.values
    assert values["MFR URL"] == "https://diablotools.com/products/DCB518ASTS06G"
    assert values["MANUFACTURER_NAME"] == "Freud Inc"
    assert values["BRAND_NAME"] == "Diablo"
    assert values["MANUFACTURER_PART_NUMBER"] == "DCB518ASTS06G"
    assert values["Dept"] == "Tools"
    assert values["Class"] == "Industrial"
    assert values["Fine"] == "General"
    assert values["Classpath"] == "Tools > Industrial > General"
    assert values["SHORT_DESC"] == "Diablo Sanding Belt 6-Pack"
    assert values["LONG_DESC1"] == "Diablo premium sanding belts for aggressive stock removal."
    assert values["ITEM_FEATURES_1"] == "Fast material removal"
    assert values["ITEM_FEATURES_2"] == "Stearate anti-clog coating"
    assert values["ATTRIBUTE_LABEL 1"] == "Brand"
    assert values["ATTRIBUTE_VALUE 1"] == "Diablo"
