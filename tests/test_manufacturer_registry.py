"""Unit tests for ManufacturerRegistry profile lookup and candidate route learning."""

from __future__ import annotations

from unilog_product_intelligence.retrieval.manufacturer_registry import ManufacturerRegistry


def test_manufacturer_registry_static_profiles_precedence() -> None:
    registry = ManufacturerRegistry()

    # Domain lookup for 3M
    prof_3m = registry.get_profile_by_domain(("multimedia.3m.com",))
    assert prof_3m is not None
    assert prof_3m.name == "3m"
    assert "www.3m.com" in prof_3m.domains

    # Name lookup for Milwaukee
    prof_mil = registry.get_profile("Milwaukee")
    assert prof_mil is not None
    assert prof_mil.name == "milwaukee"
    assert any("/products/{mpn}" in t for t in prof_mil.direct_path_templates)


def test_manufacturer_registry_learned_candidate_route() -> None:
    registry = ManufacturerRegistry()

    # Initially unknown manufacturer
    assert registry.get_profile("Acme Corp") is None

    # Learn a valid route with {mpn}
    registry.learn_candidate_route(
        manufacturer="Acme Corp",
        domain="acmetools.com",
        route_template="https://acmetools.com/products/{mpn}",
    )

    prof = registry.get_profile("Acme Corp")
    assert prof is not None
    assert prof.name == "Acme Corp"
    assert "acmetools.com" in prof.domains
    assert "https://acmetools.com/products/{mpn}" in prof.direct_path_templates


def test_manufacturer_registry_rejects_templates_without_mpn() -> None:
    registry = ManufacturerRegistry()

    # Template without {mpn} should be ignored
    registry.learn_candidate_route(
        manufacturer="Beta Tools",
        domain="betatools.com",
        route_template="https://betatools.com/all-products",
    )

    assert registry.get_profile("Beta Tools") is None


def test_manufacturer_registry_static_profiles_immune_to_tampering() -> None:
    registry = ManufacturerRegistry()

    # Attempting to overwrite a static profile like "3m" should be a no-op
    registry.learn_candidate_route(
        manufacturer="3M",
        domain="fake-3m.com",
        route_template="https://fake-3m.com/p/{mpn}",
    )

    prof = registry.get_profile("3M")
    assert prof is not None
    assert "fake-3m.com" not in prof.domains
