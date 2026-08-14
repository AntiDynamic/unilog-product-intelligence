import pytest

from unilog_product_intelligence.delivery import (
    DeliveryMappingPending,
    DeliverySchemaContract,
    ProductTruthDeliveryAdapter,
)
from unilog_product_intelligence.domain.truth import ProductTruth, RawInputField


def test_delivery_adapter_does_not_invent_unavailable_contract() -> None:
    adapter = ProductTruthDeliveryAdapter(DeliverySchemaContract())

    with pytest.raises(DeliveryMappingPending, match="official CSV"):
        adapter.to_record(ProductTruth(product_id="structural-test"))


def test_delivery_adapter_maps_only_observed_raw_input_headers() -> None:
    adapter = ProductTruthDeliveryAdapter(
        DeliverySchemaContract(
            available=True,
            headers=("Mfg_Part_Num", "Part_Desc", "MANUFACTURER_NAME"),
        )
    )
    product = ProductTruth(
        product_id="structural-test",
        raw_inputs=(
            RawInputField(
                field_name="Mfg_Part_Num",
                raw_value="sample-part",
                source_id="source-structural-test",
            ),
            RawInputField(
                field_name="Unobserved_Source_Field",
                raw_value="not-delivered",
                source_id="source-structural-test",
            ),
        ),
    )

    record = adapter.to_record(product)

    assert record.as_row() == ["sample-part", None, None]
