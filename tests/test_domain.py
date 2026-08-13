from unilog_product_intelligence.domain.models import ProductIdentity, ProductTruth


def test_product_truth_starts_without_fabricated_product_values() -> None:
    product = ProductTruth(identity=ProductIdentity())

    assert product.identity.manufacturer_part_number is None
    assert product.attributes == []
    assert product.sources == []
