"""Unit tests for ManufacturerRegistry trust model, VerifiedRoute, and TTL expiry."""

from __future__ import annotations

import pytest

from unilog_product_intelligence.domain.truth import SourceAuthority
from unilog_product_intelligence.retrieval.manufacturer_registry import (
    ManufacturerRegistry,
    RegistryTrustError,
)


def test_record_verified_route_success() -> None:
    registry = ManufacturerRegistry()
    route = registry.record_verified_route(
        manufacturer="Acme Corp",
        domain="acmetools.com",
        route_template="https://acmetools.com/products/{mpn}",
        evidence_id="ev-acme-1",
        source_authority=SourceAuthority.AUTHORITATIVE,
    )
    assert route is not None
    assert route.route_template == "https://acmetools.com/products/{mpn}"
    assert route.evidence_id == "ev-acme-1"
    assert route.domain == "acmetools.com"

    prof = registry.get_profile("Acme Corp")
    assert prof is not None
    assert "https://acmetools.com/products/{mpn}" in prof.direct_path_templates
    assert "acmetools.com" in prof.domains


def test_record_verified_route_missing_mpn_raises_trust_error() -> None:
    registry = ManufacturerRegistry()
    with pytest.raises(RegistryTrustError) as exc_info:
        registry.record_verified_route(
            manufacturer="Acme Corp",
            domain="acmetools.com",
            route_template="https://acmetools.com/all-products",
            evidence_id="ev-acme-1",
        )
    assert "must contain '{mpn}'" in str(exc_info.value)


def test_record_verified_route_missing_evidence_id_raises_trust_error() -> None:
    registry = ManufacturerRegistry()
    with pytest.raises(RegistryTrustError) as exc_info:
        registry.record_verified_route(
            manufacturer="Acme Corp",
            domain="acmetools.com",
            route_template="https://acmetools.com/products/{mpn}",
            evidence_id="",
        )
    assert "evidence_id is required" in str(exc_info.value)


def test_record_verified_route_static_profile_immune() -> None:
    registry = ManufacturerRegistry()
    # 3M is in static audited profiles
    result = registry.record_verified_route(
        manufacturer="3M",
        domain="fake-3m.com",
        route_template="https://fake-3m.com/p/{mpn}",
        evidence_id="ev-fake",
    )
    assert result is None

    prof = registry.get_profile("3M")
    assert prof is not None
    assert "fake-3m.com" not in prof.domains


def test_verified_route_ttl_expiry() -> None:
    registry = ManufacturerRegistry()

    # Route valid for 60 seconds
    route = registry.record_verified_route(
        manufacturer="Ephemeral Tools",
        domain="ephemeral.com",
        route_template="https://ephemeral.com/tools/{mpn}",
        evidence_id="ev-eph-1",
        ttl_seconds=60.0,
    )
    assert route is not None

    # Before expiry (now = 1010.0) -> profile available
    prof = registry.get_profile("Ephemeral Tools", now=route.verified_at + 10.0)
    assert prof is not None
    assert len(prof.direct_path_templates) == 1

    # After expiry (now = verified_at + 70.0) -> route expired and pruned
    prof_expired = registry.get_profile("Ephemeral Tools", now=route.verified_at + 70.0)
    assert prof_expired is None


def test_backward_compat_learn_candidate_route() -> None:
    registry = ManufacturerRegistry()
    registry.learn_candidate_route(
        manufacturer="Legacy Maker",
        domain="legacymaker.com",
        route_template="https://legacymaker.com/item/{mpn}",
    )
    prof = registry.get_profile("Legacy Maker")
    assert prof is not None
    assert "https://legacymaker.com/item/{mpn}" in prof.direct_path_templates
