"""Tests for verified multi-domain retrieval, strategy iteration, early stopping, and redirects.

Covers:
  - Test A: Second verified domain recovers product when first returns 404/no match
  - Test B: First verified domain succeeds -> second domain is never requested (early stop)
  - Test C: All verified domains fail -> graceful SOURCE_NOT_FOUND, both domains tracked
  - Test D: Search template fallback across multiple configured templates
  - Test E: Sitemap path fallback across multiple sitemap endpoints
  - Test F: Verified regional redirect allowed (e.g. mirka.com -> mirkausa.com)
  - Test G: Unverified regional-like redirect blocked (mirka.com -> mirkausa.example-malicious.com)
  - Test H: External redirect blocked (mirka.com -> evil.example)
  - Test I: MPN hypothesis ordering hierarchy (RAW > LOSSLESS > VERIFIED > EXPLORATORY)
  - Test J: Exploratory hypotheses remain search-only and cannot establish identity
"""

from __future__ import annotations

from typing import Any

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.models import Source, SourceAuthority, SourceType
from unilog_product_intelligence.domain.truth import ProductTruth
from unilog_product_intelligence.retrieval.core import (
    ManufacturerProfile,
    RetrievalStatus,
    SafeNetworkTargetResolver,
    SourceCache,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourceRecord,
)
from unilog_product_intelligence.retrieval.mpn_normalizer import (
    MpnHypothesis,
    MpnHypothesisType,
)
from unilog_product_intelligence.retrieval.source_discovery import (
    ManufacturerRetrievalProfile,
    MpnMatchClassification,
    ProductIdentityMatcher,
    ProductSourceDiscoveryService,
    _order_mpn_hypotheses_for_retrieval,
)


def _make_product(
    mpn: str = "ABC123",
    manufacturer: str = "Acme Corp",
    brand: str | None = "Acme",
    desc: str = "Industrial standard tool",
) -> ProductTruth:
    raw: dict[str, object] = {
        "Mfg_Part_Num": mpn,
        "Part_Desc": desc,
        "Part_Manuf": manufacturer,
    }
    if brand:
        raw["Unilog_Brand"] = brand
    return ProductTruthService().create_from_raw_input(
        "test-prod-1",
        raw,
        Source(
            source_id="input",
            source_type=SourceType.SUPPLIED_INPUT,
            authority=SourceAuthority.HIGH,
        ),
    )


class _TrackedFakeHttpResponse:
    def __init__(
        self,
        body: bytes = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
        url: str | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.code = status
        ct = "text/html" if body else "text/plain"
        self.headers = headers or {"Content-Type": ct, "ETag": '"v1"'}
        self.url = url

    def __enter__(self) -> _TrackedFakeHttpResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]

    def close(self) -> None:
        pass

    def geturl(self) -> str | None:
        return self.url


class _TrackingHttpPool:
    """Mock HTTP pool that records all requested URLs."""

    def __init__(
        self,
        routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes],
    ) -> None:
        self.routes = routes
        self.requested_urls: list[str] = []

    def __call__(self, request: Any, timeout: float = 15.0) -> _TrackedFakeHttpResponse:
        url = getattr(request, "full_url", str(request))
        self.requested_urls.append(url)
        entry = self.routes.get(url)
        if entry is None:
            return _TrackedFakeHttpResponse(body=b"", status=404, url=url)
        if isinstance(entry, bytes):
            return _TrackedFakeHttpResponse(body=entry, status=200, url=url)
        status, body, headers = entry
        return _TrackedFakeHttpResponse(body=body, status=status, headers=headers, url=url)


class _AllowAllResolver(SafeNetworkTargetResolver):
    def validate(self, url: str) -> None:
        pass


def _make_fetcher(pool: _TrackingHttpPool) -> SourceFetcher:
    fetcher = SourceFetcher(
        cache=SourceCache(),
        resolver=_AllowAllResolver(),
        requests_per_second=1_000.0,
    )
    fetcher.opener = pool
    fetcher._custom_opener = False
    return fetcher


# ==============================================================================
# TEST A: Second Verified Domain Recovers Product
# ==============================================================================


def test_multi_domain_test_a_second_verified_domain_recovers_product() -> None:
    """When global domain returns 404 on direct paths/search, US domain recovers product."""
    us_product_url = "https://manufacturer-us.example/products/ABC123"
    us_html = (
        b"<!DOCTYPE html><html><head><title>ABC123 - Manufacturer US</title></head>"
        b"<body><h1>ABC123</h1><p>Manufacturer Corp Part Number: ABC123</p></body></html>"
    )

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        us_product_url: us_html,
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)
    service = ProductSourceDiscoveryService(fetcher)

    product = _make_product(mpn="ABC123", manufacturer="Manufacturer Corp")
    profile = ManufacturerProfile(
        manufacturer_id="mfg-1",
        canonical_name="Manufacturer Corp",
        verified_domains=("manufacturer-global.example", "manufacturer-us.example"),
    )

    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    winner = candidates[0]
    assert winner.matched_mpn is True
    assert winner.identity_score >= 0.8
    assert "manufacturer-us.example" in winner.url
    assert service.selected_domain == "manufacturer-us.example"
    assert "manufacturer-global.example" in service.domains_attempted
    assert "manufacturer-us.example" in service.domains_attempted


# ==============================================================================
# TEST B: First Verified Domain Succeeds -> Early Stop
# ==============================================================================


def test_multi_domain_test_b_first_verified_domain_succeeds_early_stop() -> None:
    """When global domain returns exact product, US domain is never requested."""
    global_url = "https://manufacturer-global.example/products/ABC123"
    global_html = (
        b"<!DOCTYPE html><html><head><title>ABC123 - Global</title></head>"
        b"<body><h1>ABC123</h1><p>Manufacturer Corp Model: ABC123</p></body></html>"
    )
    us_url = "https://manufacturer-us.example/products/ABC123"
    us_html = (
        b"<!DOCTYPE html><html><head><title>ABC123 - US</title></head>"
        b"<body><h1>ABC123</h1><p>Manufacturer Corp Model: ABC123</p></body></html>"
    )

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        global_url: global_html,
        us_url: us_html,
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)
    service = ProductSourceDiscoveryService(fetcher)

    product = _make_product(mpn="ABC123", manufacturer="Manufacturer Corp")
    profile = ManufacturerProfile(
        manufacturer_id="mfg-1",
        canonical_name="Manufacturer Corp",
        verified_domains=("manufacturer-global.example", "manufacturer-us.example"),
    )

    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    assert candidates[0].matched_mpn is True
    assert "manufacturer-global.example" in candidates[0].url
    assert service.selected_domain == "manufacturer-global.example"
    assert service.domains_attempted == ("manufacturer-global.example",)

    # US domain must NEVER have been requested
    assert not any("manufacturer-us.example" in u for u in pool.requested_urls)


# ==============================================================================
# TEST C: All Verified Domains Fail -> Graceful Exhaustion
# ==============================================================================


def test_multi_domain_test_c_all_verified_domains_fail() -> None:
    """When all verified domains return 404, both appear in domain trace, no crash."""
    pool = _TrackingHttpPool({})
    fetcher = _make_fetcher(pool)
    service = ProductSourceDiscoveryService(fetcher)

    product = _make_product(mpn="ABC123", manufacturer="Manufacturer Corp")
    profile = ManufacturerProfile(
        manufacturer_id="mfg-1",
        canonical_name="Manufacturer Corp",
        verified_domains=("manufacturer-global.example", "manufacturer-us.example"),
    )

    candidates = service.discover(product, profile)

    assert candidates == []
    assert "manufacturer-global.example" in service.domains_attempted
    assert "manufacturer-us.example" in service.domains_attempted
    assert "manufacturer-global.example" in service.domain_attempt_failure_reasons
    assert "manufacturer-us.example" in service.domain_attempt_failure_reasons


# ==============================================================================
# TEST D: Search Template Fallback
# ==============================================================================


def test_multi_domain_test_d_search_template_fallback() -> None:
    """When template 1 and 2 yield no results, template 3 returns product link."""
    tmpl1_url = "https://manufacturer.example/search?q=ABC123"
    tmpl2_url = "https://manufacturer.example/Search/Products?q=ABC123"
    tmpl3_url = "https://manufacturer.example/search?query=ABC123"
    product_url = "https://manufacturer.example/item-catalog/ABC123"

    empty_search_html = b"<html><body><p>0 results found</p></body></html>"
    success_search_html = (
        b'<html><body><a href="https://manufacturer.example/item-catalog/ABC123">'
        b"ABC123 Heavy Duty Tool</a></body></html>"
    )
    product_html = (
        b"<html><head><title>ABC123</title></head>"
        b"<body><h1>ABC123</h1><p>Manufacturer Corp Part ABC123</p></body></html>"
    )

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        tmpl1_url: empty_search_html,
        tmpl2_url: empty_search_html,
        tmpl3_url: success_search_html,
        product_url: product_html,
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)

    # Retrieval profile with 3 search templates and no direct match
    retrieval_profile = ManufacturerRetrievalProfile(
        name="test-mfg",
        domains=("manufacturer.example",),
        search_url_templates=(
            "https://manufacturer.example/search?q={mpn}",
            "https://manufacturer.example/Search/Products?q={mpn}",
            "https://manufacturer.example/search?query={mpn}",
        ),
    )
    service = ProductSourceDiscoveryService(fetcher)

    # Mock retrieval profile lookup for this test domain
    from unilog_product_intelligence.retrieval import source_discovery

    orig_profiles = source_discovery._RETRIEVAL_PROFILES
    try:
        source_discovery._RETRIEVAL_PROFILES = (retrieval_profile,)
        product = _make_product(mpn="ABC123", manufacturer="Manufacturer Corp")
        profile = ManufacturerProfile(
            manufacturer_id="mfg-1",
            canonical_name="Manufacturer Corp",
            verified_domains=("manufacturer.example",),
        )

        candidates = service.discover(product, profile)

        assert len(candidates) > 0
        assert candidates[0].matched_mpn is True
        assert candidates[0].url == product_url
        assert tmpl1_url in pool.requested_urls
        assert tmpl2_url in pool.requested_urls
        assert tmpl3_url in pool.requested_urls
    finally:
        source_discovery._RETRIEVAL_PROFILES = orig_profiles


# ==============================================================================
# TEST E: Sitemap Path Fallback
# ==============================================================================


def test_multi_domain_test_e_sitemap_path_fallback() -> None:
    """When /sitemap.xml has no match, /sitemap_index.xml yields matching product URL."""
    sm1_url = "https://manufacturer.example/sitemap.xml"
    sm2_url = "https://manufacturer.example/sitemap_index.xml"
    product_url = "https://manufacturer.example/catalog/deep-ABC123"

    sm1_xml = (
        b"<?xml version='1.0' encoding='UTF-8'?>"
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://manufacturer.example/products/XYZ999</loc></url>"
        b"</urlset>"
    )
    sm2_xml = (
        b"<?xml version='1.0' encoding='UTF-8'?>"
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://manufacturer.example/catalog/deep-ABC123</loc></url>"
        b"</urlset>"
    )
    product_html = (
        b"<html><head><title>ABC123</title></head>"
        b"<body><h1>ABC123</h1><p>Manufacturer Corp Part ABC123</p></body></html>"
    )

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        sm1_url: sm1_xml,
        sm2_url: sm2_xml,
        product_url: product_html,
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)
    service = ProductSourceDiscoveryService(fetcher)

    product = _make_product(mpn="ABC123", manufacturer="Manufacturer Corp")
    profile = ManufacturerProfile(
        manufacturer_id="mfg-1",
        canonical_name="Manufacturer Corp",
        verified_domains=("manufacturer.example",),
    )

    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    assert candidates[0].matched_mpn is True
    assert candidates[0].url == product_url
    assert sm1_url in pool.requested_urls
    assert sm2_url in pool.requested_urls


# ==============================================================================
# TEST F: Verified Regional Redirect Allowed
# ==============================================================================


def test_multi_domain_test_f_verified_regional_redirect() -> None:
    """Redirect from mirka.com to mirkausa.com is allowed when both are verified domains."""
    initial_url = "https://mirka.com/products/ABC123"
    redirect_url = "https://mirkausa.com/products/ABC123"
    product_html = (
        b"<!DOCTYPE html><html><head><title>Mirka ABC123</title></head>"
        b"<body><h1>ABC123</h1><p>Mirka Abrasives MPN: ABC123</p></body></html>"
    )

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        initial_url: (301, b"", {"Location": redirect_url}),
        redirect_url: product_html,
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)

    source = SourceRecord(
        canonical_url=initial_url,
        original_url=initial_url,
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="m-mirka",
        manufacturer_domain="mirka.com",
        verified_domains=("mirka.com", "mirkausa.com"),
    )

    result = fetcher.fetch(source)

    assert result.source.retrieval_status == RetrievalStatus.SUCCESS
    assert result.source.canonical_url == redirect_url
    assert result.source.manufacturer_domain == "mirkausa.com"


# ==============================================================================
# TEST G: Unverified Regional-Like Redirect Blocked
# ==============================================================================


def test_multi_domain_test_g_unverified_regional_like_redirect_blocked() -> None:
    """Redirect to lookalike unverified domain is blocked."""
    initial_url = "https://mirka.com/products/ABC123"
    malicious_url = "https://mirkausa.example-malicious.com/products/ABC123"

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        initial_url: (301, b"", {"Location": malicious_url}),
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)

    source = SourceRecord(
        canonical_url=initial_url,
        original_url=initial_url,
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="m-mirka",
        manufacturer_domain="mirka.com",
        verified_domains=("mirka.com", "mirkausa.com"),
    )

    result = fetcher.fetch(source)

    assert result.source.retrieval_status == RetrievalStatus.FAILED
    assert result.error == "redirect_external_domain"


# ==============================================================================
# TEST H: External Redirect Blocked
# ==============================================================================


def test_multi_domain_test_h_external_redirect_blocked() -> None:
    """Redirect to third-party domain is blocked."""
    initial_url = "https://mirka.com/products/ABC123"
    evil_url = "https://evil.example/products/ABC123"

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        initial_url: (301, b"", {"Location": evil_url}),
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)

    source = SourceRecord(
        canonical_url=initial_url,
        original_url=initial_url,
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="m-mirka",
        manufacturer_domain="mirka.com",
        verified_domains=("mirka.com", "mirkausa.com"),
    )

    result = fetcher.fetch(source)

    assert result.source.retrieval_status == RetrievalStatus.FAILED
    assert result.error == "redirect_external_domain"


# ==============================================================================
# TEST I: MPN Hypothesis Order
# ==============================================================================


def test_multi_domain_test_i_mpn_hypothesis_order() -> None:
    """Hypotheses are ordered RAW > LOSSLESS > VERIFIED_TRANSFORM > EXPLORATORY."""
    h_exploratory = MpnHypothesis(
        value="123456",
        hypothesis_type=MpnHypothesisType.EXPLORATORY_PREFIX_STRIP,
        confidence=0.50,
        is_lossless=False,
        identity_eligible=False,
    )
    h_verified = MpnHypothesis(
        value="7100075678",
        hypothesis_type=MpnHypothesisType.VERIFIED_MANUFACTURER_TRANSFORM,
        confidence=0.90,
        is_lossless=False,
        identity_eligible=True,
    )
    h_lossless = MpnHypothesis(
        value="49940013",
        hypothesis_type=MpnHypothesisType.LOSSLESS_NORMALIZED,
        confidence=0.98,
        is_lossless=True,
        identity_eligible=True,
    )
    h_raw = MpnHypothesis(
        value="49-94-0013",
        hypothesis_type=MpnHypothesisType.RAW,
        confidence=1.0,
        is_lossless=True,
        identity_eligible=True,
    )

    ordered = _order_mpn_hypotheses_for_retrieval(
        [h_exploratory, h_verified, h_lossless, h_raw]
    )

    assert ordered[0].hypothesis_type == MpnHypothesisType.RAW
    assert ordered[1].hypothesis_type == MpnHypothesisType.LOSSLESS_NORMALIZED
    assert ordered[2].hypothesis_type == MpnHypothesisType.VERIFIED_MANUFACTURER_TRANSFORM
    assert ordered[3].hypothesis_type == MpnHypothesisType.EXPLORATORY_PREFIX_STRIP


# ==============================================================================
# TEST J: Exploratory Hypotheses Remain Search-Only
# ==============================================================================


def test_multi_domain_test_j_exploratory_hypotheses_remain_search_only() -> None:
    """Exploratory hypotheses (e.g. generic prefix strip) cannot verify product identity."""
    matcher = ProductIdentityMatcher()
    product = _make_product(mpn="AB-123456", manufacturer="Acme Corp")
    doc = type(
        "Document",
        (),
        {
            "title": "Acme 123456 Item",
            "chunks": [type("Chunk", (), {"text": "Acme Corp product 123456"})()],
            "structured_metadata": {},
        },
    )()

    match = matcher.match(product, doc)

    assert match.matched_mpn is False
    assert match.mpn_match_type == MpnMatchClassification.EXPLORATORY_ONLY
    assert match.identity_score < 0.6
    assert match.rejection_reason == "EXPLORATORY_MPN_UNVERIFIED"
