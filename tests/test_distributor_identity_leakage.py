"""Tests for Task 7: Prevent distributor identity leakage into final product delivery truth."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from unilog_product_intelligence.application.brand_resolver import (
    BrandManufacturerResolver,
)
from unilog_product_intelligence.application.phase65 import (
    Phase65Result,
    Phase65Status,
)
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.delivery.adapter import (
    DeliverySchemaContract,
    Phase65ResultDeliveryAdapter,
    _is_distributor_string,
)
from unilog_product_intelligence.domain.truth import (
    IdentityField,
    ProductIdentity,
    ProductTruth,
    Source,
    SourceAuthority,
    SourceType,
    ValueStatus,
)


def _make_raw_product(
    pid: str,
    mpn: str,
    part_manuf: str,
    part_desc: str,
    unilog_brand: str = "-- No Unilog Brand --",
) -> ProductTruth:
    service = ProductTruthService()
    source = Source(
        source_id="input-csv",
        source_type=SourceType.SUPPLIED_INPUT,
        authority=SourceAuthority.LOW,
    )
    raw_fields = {
        "Mfg_Part_Num": mpn,
        "Part_Manuf": part_manuf,
        "Part_Desc": part_desc,
        "Unilog_Brand": unilog_brand,
        "E1_Brand": "-- Unbranded --",
        "DIB_Brand": "-- No DIB Brand --",
    }
    return service.create_from_raw_input(pid, raw_fields, source)


def test_wke100hwa_lg_washtower_demasking() -> None:
    """Fixture 1: WKE100HWA with distributor resolves to LG."""
    resolver = BrandManufacturerResolver()
    resolved = resolver.resolve(
        part_manuf="Appliance Dealers Cooperative (APPDE)",
        part_desc="Single Unit Front Load WashTower 4.5 Cu. Ft. Washer",
        mpn="WKE100HWA",
    )

    assert resolved.is_distributor is True
    assert resolved.manufacturer == "lg"
    assert resolved.brand == "LG"

    # Verify adapter delivery output
    schema_path = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "research"
        / "delivery-schema.json"
    )
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    product = _make_raw_product(
        "p-lg",
        "WKE100HWA",
        "Appliance Dealers Cooperative (APPDE)",
        "Single Unit Front Load WashTower 4.5 Cu. Ft. Washer",
    )
    res = MagicMock(spec=Phase65Result)
    res.product_truth = product
    res.manufacturer_job = None
    res.status = Phase65Status.ENRICHED
    res.resolved_manufacturer = "LG"
    res.resolved_brand = "LG"
    res.is_distributor_masked = True

    record = adapter.to_record(res)
    assert record.values["MANUFACTURER_NAME"] == "LG"
    assert record.values["BRAND_NAME"] == "LG"
    # Ensure distributor name is NOT published
    assert "Cooperative" not in str(record.values["MANUFACTURER_NAME"])


def test_ff7011wn_speed_queen_demasking() -> None:
    """Fixture 2: FF7011WN with distributor resolves to Speed Queen."""
    resolver = BrandManufacturerResolver()
    resolved = resolver.resolve(
        part_manuf="Appliance Dealers Cooperative (APPDE)",
        part_desc="Front Load Washer with Dynamic Balancing and Sanitize Cycle White",
        mpn="FF7011WN",
    )

    assert resolved.is_distributor is True
    assert resolved.manufacturer == "speed queen"
    assert resolved.brand == "Speed Queen"

    schema_path = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "research"
        / "delivery-schema.json"
    )
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    product = _make_raw_product(
        "p-sq",
        "FF7011WN",
        "Appliance Dealers Cooperative (APPDE)",
        "Front Load Washer with Dynamic Balancing and Sanitize Cycle White",
    )
    res = MagicMock(spec=Phase65Result)
    res.product_truth = product
    res.manufacturer_job = None
    res.status = Phase65Status.ENRICHED
    res.resolved_manufacturer = "Speed Queen"
    res.resolved_brand = "Speed Queen"
    res.is_distributor_masked = True

    record = adapter.to_record(res)
    assert record.values["MANUFACTURER_NAME"] == "Speed Queen"
    assert record.values["BRAND_NAME"] == "Speed Queen"
    assert "Appliance" not in str(record.values["MANUFACTURER_NAME"])


def test_ptd70gbptdg_ge_profile_demasking() -> None:
    """Fixture 3: PTD70GBPTDG with distributor resolves to GE Appliances / GE Profile."""
    resolver = BrandManufacturerResolver()
    resolved = resolver.resolve(
        part_manuf="Appliance Dealers Cooperative (APPDE)",
        part_desc="7.4 Cu. Ft. Capacity Gas Dryer with Sanitize and Wrinkle Care",
        mpn="PTD70GBPTDG",
    )

    assert resolved.is_distributor is True
    assert resolved.manufacturer == "ge appliances"
    assert resolved.brand == "GE Profile"

    schema_path = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "research"
        / "delivery-schema.json"
    )
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    product = _make_raw_product(
        "p-ge",
        "PTD70GBPTDG",
        "Appliance Dealers Cooperative (APPDE)",
        "7.4 Cu. Ft. Capacity Gas Dryer with Sanitize and Wrinkle Care",
    )
    res = MagicMock(spec=Phase65Result)
    res.product_truth = product
    res.manufacturer_job = None
    res.status = Phase65Status.ENRICHED
    res.resolved_manufacturer = "GE Appliances"
    res.resolved_brand = "GE Profile"
    res.is_distributor_masked = True

    record = adapter.to_record(res)
    assert record.values["MANUFACTURER_NAME"] == "GE Appliances"
    assert record.values["BRAND_NAME"] == "GE Profile"


def test_unresolved_distributor_never_published_as_manufacturer() -> None:
    """Test when distributor is unresolved, MANUFACTURER_NAME is None (never distributor)."""
    schema_path = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "research"
        / "delivery-schema.json"
    )
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    # Product with unresolvable distributor name in raw Part_Manuf and identity
    product = _make_raw_product(
        "p-unresolved",
        "UNKNOWN-SKU-999",
        "Appliance Dealers Cooperative (APPDE)",
        "Generic Unknown Replacement Part 100",
    )
    product.identity = ProductIdentity(
        manufacturer=IdentityField(
            raw_value="Appliance Dealers Cooperative",
            normalized_value="Appliance Dealers Cooperative",
            status=ValueStatus.MISSING,
        ),
        brand=IdentityField(
            raw_value="Appliance Dealers Cooperative",
            normalized_value="Appliance Dealers Cooperative",
            status=ValueStatus.MISSING,
        ),
    )

    res = MagicMock(spec=Phase65Result)
    res.product_truth = product
    res.manufacturer_job = None
    res.status = Phase65Status.REVIEW_REQUIRED
    res.resolved_manufacturer = None
    res.resolved_brand = None
    res.is_distributor_masked = True

    record = adapter.to_record(res)
    # MUST be None and NOT leak distributor string
    assert record.values["MANUFACTURER_NAME"] is None
    assert record.values["BRAND_NAME"] is None


def test_is_distributor_string_detection() -> None:
    """Test _is_distributor_string flags distributor phrases and allows real manufacturers."""
    assert _is_distributor_string("Appliance Dealers Cooperative") is True
    assert _is_distributor_string("Jam Industrial Supply LLC") is True
    assert _is_distributor_string("Builders FirstSource") is True
    assert _is_distributor_string("Boise Cascade Building Materials") is True
    assert _is_distributor_string("L & W Supply") is True
    assert _is_distributor_string("W.W. Grainger") is True
    assert _is_distributor_string("Ferguson Enterprises") is True

    # Real manufacturers must NOT be flagged
    assert _is_distributor_string("DeWalt") is False
    assert _is_distributor_string("Milwaukee") is False
    assert _is_distributor_string("LG Electronics") is False
    assert _is_distributor_string("Speed Queen") is False
    assert _is_distributor_string("GE Appliances") is False
    assert _is_distributor_string("Frigidaire") is False
    assert _is_distributor_string("Whirlpool") is False
    assert _is_distributor_string("Diablo") is False
