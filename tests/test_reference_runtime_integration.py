"""Tests for ReferencePack production runtime integration (Phase 6 Foundation)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from openpyxl import Workbook
from scripts.run_pipeline import _build_pipeline

from unilog_product_intelligence.application.evaluation import (
    DeterministicEvaluationProvider,
)
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.models import Source, SourceAuthority, SourceType
from unilog_product_intelligence.domain.truth import (
    ProductClassification,
    ProductTruth,
)
from unilog_product_intelligence.enrichment.models import ReferenceAvailability
from unilog_product_intelligence.enrichment.planner import AttributePlanner
from unilog_product_intelligence.enrichment.reference import (
    CategoryLovPack,
    GlobalLovIndex,
    LovAttributeRule,
    ReferencePack,
    ReferenceType,
    UomRecord,
    UomStandardMap,
)
from unilog_product_intelligence.retrieval.core import SourceFetcher
from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService


def _create_test_uom_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "UOM Standards"
    ws.append(["Approved UOM", "Measurement Type", "Capture Form", "Example", "Synonyms"])
    ws.append(["V", "Voltage", "V", "120 V", "Volt, Volts"])
    ws.append(["in.", "Length", "in.", "4 in.", "Inch, Inches, \""])
    ws.append(["A", "Current", "A", "15 A", "Amp, Amps"])
    wb.save(path)


def _create_test_global_lov_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Global LOV"
    ws.append([
        "Classpath",
        "Leaf Node",
        "Attribute Label",
        "Attribute Values",
        "Normalized Label",
        "Normalized Values",
        "Filtering",
        "Guidelines",
        "Remarks",
        "Allowed UOM",
    ])
    ws.append([
        "Abrasives > Cut-Off Wheels",
        "Cut-Off Wheels",
        "Abrasive Material",
        "Aluminum Oxide\nSilicon Carbide\nCeramic",
        "Abrasive Material",
        "Aluminum Oxide\nSilicon Carbide\nCeramic",
        "Yes",
        "Must be verified manufacturer material",
        "Required attribute",
        "none",
    ])
    wb.save(path)


def _make_test_product(mpn: str = "49-94-0013") -> ProductTruth:
    source = Source(
        source_id="src-1",
        source_type=SourceType.SUPPLIED_INPUT,
        authority=SourceAuthority.HIGH,
    )
    truth = ProductTruthService().create_from_raw_input(
        f"prod-{mpn}",
        {
            "Mfg_Part_Num": mpn,
            "Part_Desc": "4-1/2 in. Cut-Off Wheel",
            "Unilog_Brand": "Milwaukee Tool",
            "Part_Manuf": "Milwaukee Tool",
        },
        source,
    )
    return ProductTruthService().add_classification(
        truth,
        ProductClassification(
            class_name="Cut-Off Wheels",
            classpath=("Abrasives", "Cut-Off Wheels"),
        ),
    )


# ==============================================================================
# TEST A — PACK IS INJECTED
# ==============================================================================


def test_reference_pack_injected_into_pipeline(tmp_path: Path) -> None:
    """Discovers ReferencePack and ensures it is injected into AttributePlanner."""
    uom_file = tmp_path / "Unilog_Master_UOM_Standards_Abbreviations_and_Terms.xlsx"
    _create_test_uom_workbook(uom_file)

    pack = ReferencePack.discover([tmp_path])
    assert pack.availability == ReferenceAvailability.REFERENCE_AVAILABLE
    assert pack.uom_available

    provider = DeterministicEvaluationProvider()
    truth_service = ProductTruthService()
    fetcher = SourceFetcher()
    source_disc = ProductSourceDiscoveryService(fetcher=fetcher)

    pipeline = _build_pipeline(
        provider=provider,
        truth_service=truth_service,
        fetcher=fetcher,
        source_disc=source_disc,
        reference_pack=pack,
        live=False,
    )

    assert pipeline.enrichment.planner.reference_pack is pack
    assert (
        pipeline.enrichment.planner.reference_pack.availability
        == ReferenceAvailability.REFERENCE_AVAILABLE
    )


# ==============================================================================
# TEST B — AVAILABLE UOM IS USED
# ==============================================================================


def test_available_uom_is_used() -> None:
    """Approved UOM from injected ReferencePack is recognized by the planner."""
    uom_map = UomStandardMap(
        records=(UomRecord(approved_uom="V", measurement_type="Voltage"),),
        approved_uoms=frozenset({"v"}),
        canonical_uom_map={"v": "V", "volt": "V", "volts": "V"},
    )
    pack = ReferencePack(
        availability=ReferenceAvailability.REFERENCE_AVAILABLE,
        uom_standards=uom_map,
        status={ReferenceType.UOM_STANDARD: ReferenceAvailability.REFERENCE_AVAILABLE},
    )

    planner = AttributePlanner(reference_pack=pack)
    assert planner.reference_pack.uom_standards is not None
    assert planner.reference_pack.uom_standards.is_approved("V")
    assert planner.reference_pack.uom_standards.normalize("volts") == "V"


# ==============================================================================
# TEST C — GLOBAL LOV IS USED
# ==============================================================================


def test_global_lov_is_used(tmp_path: Path) -> None:
    """Allowed values from Global LOV workbook are planned and enforced."""
    lov_file = tmp_path / "Unicat_Lov_v1_0_Updated_With_Remarks.xlsx"
    _create_test_global_lov_workbook(lov_file)

    pack = ReferencePack.discover([tmp_path])
    assert pack.availability == ReferenceAvailability.REFERENCE_AVAILABLE
    assert pack.status.get(ReferenceType.GLOBAL_LOV) == ReferenceAvailability.REFERENCE_AVAILABLE

    product = _make_test_product()
    planner = AttributePlanner(reference_pack=pack)
    plans = planner.plan(product)

    assert len(plans) > 0
    mat_plan = next((p for p in plans if "abrasive_material" in p.attribute_id), None)
    assert mat_plan is not None
    assert "Aluminum Oxide" in mat_plan.allowed_values
    assert "Silicon Carbide" in mat_plan.allowed_values
    assert "GLOBAL_LOV" in mat_plan.schema_source


# ==============================================================================
# TEST D — CATEGORY LOV OVERRIDES GLOBAL
# ==============================================================================


def test_category_lov_overrides_global() -> None:
    """Category-specific LOV rules take precedence over global rules."""
    cat_pack = CategoryLovPack(
        category_name="Faucets",
        attribute_rules={
            "faucet type": LovAttributeRule(
                classpath=("Plumbing", "Faucets"),
                leaf_node="Faucets",
                attribute_label="Faucet Type",
                attribute_values=("Single Handle", "Pull-Down"),
            )
        },
    )
    global_index = GlobalLovIndex(
        rules=(
            LovAttributeRule(
                classpath=("Plumbing", "Faucets"),
                leaf_node="Faucets",
                attribute_label="Faucet Type",
                attribute_values=("Commercial", "Residential"),
            ),
        )
    )
    pack = ReferencePack(
        availability=ReferenceAvailability.REFERENCE_AVAILABLE,
        global_lov=global_index,
        category_lovs={"faucets": cat_pack},
    )

    allowed = pack.get_allowed_values(
        "Faucet Type", classpath=("Plumbing", "Faucets"), category="Faucets"
    )
    assert set(allowed) == {"Pull-Down", "Single Handle"}
    assert "Commercial" not in allowed


# ==============================================================================
# TEST E — MISSING REFERENCE FILES FAIL CLOSED
# ==============================================================================


def test_missing_reference_files_fail_closed(tmp_path: Path) -> None:
    """Empty reference directory results in fail-closed REFERENCE_UNAVAILABLE."""
    empty_dir = tmp_path / "empty_ref"
    empty_dir.mkdir()

    pack = ReferencePack.discover([empty_dir])
    assert pack.availability == ReferenceAvailability.REFERENCE_UNAVAILABLE
    assert not pack.uom_available
    assert not pack.lov_available
    assert not pack.allowed_values
    assert not pack.allowed_uom

    planner = AttributePlanner(reference_pack=pack)
    assert planner.reference_pack.availability == ReferenceAvailability.REFERENCE_UNAVAILABLE


# ==============================================================================
# TEST F — SINGLE PACK INSTANCE REUSE
# ==============================================================================


def test_single_pack_instance_shared_with_enrichment_and_descriptions() -> None:
    """AttributePlanner and DescriptionService receive the exact same ReferencePack instance."""
    pack = ReferencePack(availability=ReferenceAvailability.REFERENCE_AVAILABLE, files={})
    provider = DeterministicEvaluationProvider()
    truth_service = ProductTruthService()
    fetcher = SourceFetcher()
    source_disc = ProductSourceDiscoveryService(fetcher=fetcher)

    pipeline = _build_pipeline(
        provider=provider,
        truth_service=truth_service,
        fetcher=fetcher,
        source_disc=source_disc,
        reference_pack=pack,
        live=False,
    )

    product = _make_test_product()
    res = pipeline.enrichment.enrich(product)

    assert pipeline.enrichment.planner.reference_pack is pack
    assert res.product_truth is not None


# ==============================================================================
# TEST G — 1000-ROW STYLE REUSE
# ==============================================================================


def test_reference_discovery_called_once_and_reused_across_multiple_rows(tmp_path: Path) -> None:
    """Discover is called once at startup and the resulting ReferencePack is reused across rows."""
    uom_file = tmp_path / "Unilog_Master_UOM_Standards_Abbreviations_and_Terms.xlsx"
    _create_test_uom_workbook(uom_file)

    discover_spy = MagicMock(wraps=ReferencePack.discover)
    discovered_pack = discover_spy([tmp_path])

    # Assert discover was called once during startup
    assert discover_spy.call_count == 1

    provider = DeterministicEvaluationProvider()
    truth_service = ProductTruthService()
    fetcher = SourceFetcher()
    source_disc = ProductSourceDiscoveryService(fetcher=fetcher)

    pipeline = _build_pipeline(
        provider=provider,
        truth_service=truth_service,
        fetcher=fetcher,
        source_disc=source_disc,
        reference_pack=discovered_pack,
        live=False,
    )

    # Process 5 rows through the pipeline
    for i in range(5):
        product = _make_test_product(mpn=f"49-94-001{i}")
        pipeline.run(product)

    # Discovery must NOT have been called again for any row
    assert discover_spy.call_count == 1
