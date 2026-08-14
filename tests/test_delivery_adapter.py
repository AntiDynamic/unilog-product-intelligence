import pytest

from unilog_product_intelligence.delivery import (
    DeliveryMappingPending,
    DeliverySchemaContract,
    ProductTruthDeliveryAdapter,
)
from unilog_product_intelligence.domain.truth import ProductTruth


def test_delivery_adapter_does_not_invent_unavailable_contract() -> None:
    adapter = ProductTruthDeliveryAdapter(DeliverySchemaContract())

    with pytest.raises(DeliveryMappingPending, match="official CSV"):
        adapter.to_record(ProductTruth(product_id="structural-test"))
