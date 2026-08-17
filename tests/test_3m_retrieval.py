"""Tests for 3M dynamic product retrieval in Phase 5.

Covers:
  - Test A: 3M verified transform search (3MABR-7100075678 -> 7100075678) with raw MPN preserved
  - Test B: 3M product page exact identity verification (VERIFIED_TRANSFORMED, score >= 0.8)
  - Test C: Wrong 3M product (off-by-one MPN 7100075679 rejected)
  - Test D: Raw MPN search attempted before transformed fallback
  - Test E: Search endpoint failure (404/5xx) falls back gracefully
  - Test F: Client-shell / JSON-script catalog discovery
  - Test G: Document / technical data sheet fallback on multimedia.3m.com
  - Test H: Unverified third-party domain blocked
  - Test I: Duplicate search URL deduplication
"""

from __future__ import annotations

import contextlib
from typing import Any

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.models import Source, SourceAuthority, SourceType
from unilog_product_intelligence.domain.truth import ProductTruth
from unilog_product_intelligence.retrieval.core import (
    DocumentChunk,
    DocumentLink,
    ManufacturerProfile,
    ParsedDocument,
    SafeNetworkTargetResolver,
    SourceCache,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourcePolicy,
    SourceRecord,
    canonicalize_url,
)
from unilog_product_intelligence.retrieval.mpn_normalizer import (
    MpnNormalizer,
)
from unilog_product_intelligence.retrieval.source_discovery import (
    MpnMatchClassification,
    ProductIdentityMatcher,
    ProductSourceDiscoveryService,
    ThreeMRetrievalStrategy,
)


def _make_3m_product(
    mpn: str = "3MABR-7100075678",
    manufacturer: str = "Jam Industrial Supply LLC (JAMIN)",
    brand: str = "3M",
    desc: str = "3M 775L Stikit Film Disc 5in P150 Holeless 100/Pkg - Cubitron II",
) -> ProductTruth:
    raw: dict[str, object] = {
        "Mfg_Part_Num": mpn,
        "Part_Desc": desc,
        "Part_Manuf": manufacturer,
        "Unilog_Brand": brand,
    }
    return ProductTruthService().create_from_raw_input(
        "3m-test-prod",
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
        is_pdf = url and url.endswith(".pdf")
        ct = "application/pdf" if is_pdf else ("text/html" if body else "text/plain")
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
    """Mock HTTP pool that records all requested URLs and normalizes route lookup."""

    def __init__(
        self,
        routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes],
    ) -> None:
        self.routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {}
        for k, v in routes.items():
            self.routes[k] = v
            with contextlib.suppress(ValueError):
                self.routes[canonicalize_url(k)] = v
        self.requested_urls: list[str] = []

    def __call__(self, request: Any, timeout: float = 15.0) -> _TrackedFakeHttpResponse:
        url = getattr(request, "full_url", str(request))
        self.requested_urls.append(url)
        entry = self.routes.get(url)
        if entry is None:
            with contextlib.suppress(ValueError):
                entry = self.routes.get(canonicalize_url(url))
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
# TEST A: 3M Verified Transform Search (3MABR-7100075678 -> 7100075678)
# ==============================================================================


def test_3m_test_a_verified_transform_search() -> None:
    """3M search uses transformed MPN 7100075678, preserves raw MPN in ProductTruth."""
    search_url = "https://www.3m.com/3M/en_US/search/?q=7100075678"
    product_url = "https://www.3m.com/3M/en_US/p/d/v000188684"

    search_html = (
        b'<html><body><div class="search-results">'
        b'<a href="/3M/en_US/p/d/v000188684">'
        b"3M Cubitron II Stikit Film Disc 775L - Part 7100075678</a>"
        b"</div></body></html>"
    )
    product_html = (
        b"<!DOCTYPE html><html><head><title>3M Cubitron II Film Disc 775L</title></head>"
        b"<body><h1>3M Cubitron II Stikit Film Disc 775L</h1>"
        b"<p>3M Stock Number: 7100075678</p>"
        b"<p>Brand: 3M | Manufacturer: 3M Company</p>"
        b"<p>High performance 5 inch 150+ grit sanding disc</p></body></html>"
    )

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        search_url: search_html,
        product_url: product_html,
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)
    service = ProductSourceDiscoveryService(fetcher)

    product = _make_3m_product(mpn="3MABR-7100075678")
    profile = ManufacturerProfile(
        manufacturer_id="3m",
        canonical_name="3M",
        verified_domains=("3m.com", "www.3m.com"),
    )

    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    winner = candidates[0]
    assert winner.matched_mpn is True
    assert winner.identity_score >= 0.6
    assert winner.mpn_match_type == MpnMatchClassification.VERIFIED_TRANSFORMED
    assert canonicalize_url(winner.url) == canonicalize_url(product_url)

    # Raw MPN in ProductTruth must remain preserved
    assert product.raw_value("Mfg_Part_Num") == "3MABR-7100075678"

    # Transformed MPN was used in search URL
    assert any("7100075678" in u for u in pool.requested_urls)


# ==============================================================================
# TEST B: 3M Product Page Exact Identity Verification
# ==============================================================================


def test_3m_test_b_product_page_identity() -> None:
    """3M page with 7100075678, 3M brand and context produces VERIFIED_TRANSFORMED."""
    matcher = ProductIdentityMatcher()
    product = _make_3m_product(
        mpn="3MABR-7100075678",
        manufacturer="3M",
        brand="3M",
        desc="3M 775L Stikit Film Disc 5in P150 Holeless 100/Pkg - Cubitron II",
    )

    doc = ParsedDocument(
        document_id="doc-3m-1",
        source_id="src-1",
        content_hash="hash-3m-1",
        parser="html",
        parser_version="v2",
        title="3M Cubitron II Stikit Film Disc 775L 7100075678",
        chunks=[
            DocumentChunk(
                document_id="doc-3m-1",
                text=(
                    "3M™ Cubitron™ II Stikit™ Film Disc 775L "
                    "3M Part Number: 7100075678. 3M Company."
                ),
            )
        ],
        structured_metadata={"meta": {"brand": "3M", "manufacturer": "3M"}},
    )

    match = matcher.match(product, doc)

    assert match.matched_mpn is True
    assert match.mpn_match_type == MpnMatchClassification.VERIFIED_TRANSFORMED
    assert match.identity_score >= 0.8
    assert match.classification in {"EXACT_MATCH", "STRONG_MATCH"}


# ==============================================================================
# TEST C: Wrong 3M Product Rejected
# ==============================================================================


def test_3m_test_c_wrong_3m_product_rejected() -> None:
    """3M page with off-by-one MPN 7100075679 is strictly rejected."""
    matcher = ProductIdentityMatcher()
    product = _make_3m_product(mpn="3MABR-7100075678", manufacturer="3M")

    doc = ParsedDocument(
        document_id="doc-3m-wrong",
        source_id="src-1",
        content_hash="hash-3m-wrong",
        parser="html",
        parser_version="v2",
        title="3M Cubitron II Film Disc 775L 7100075679",
        chunks=[
            DocumentChunk(
                document_id="doc-3m-wrong",
                text="3M Part 7100075679 Hookit disc. 3M Company.",
            )
        ],
        structured_metadata={},
    )

    match = matcher.match(product, doc)

    assert match.matched_mpn is False
    assert match.identity_score < 0.6
    assert match.classification == "WEAK_MATCH"


# ==============================================================================
# TEST D: Raw MPN Search Attempted Before Transformed Fallback
# ==============================================================================


def test_3m_test_d_raw_mpn_search_attempted() -> None:
    """Strategy attempts queries with RAW MPN before TRANSFORMED MPN."""
    strat = ThreeMRetrievalStrategy()
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("3MABR-7100075678", manufacturer_hint="3M")
    product = _make_3m_product()
    profile = ManufacturerProfile(
        manufacturer_id="3m",
        canonical_name="3M",
        verified_domains=("3m.com",),
    )

    search_urls = strat.search_urls("3m.com", hypotheses, product, profile)

    # First search queries must target raw MPN
    assert any("3MABR-7100075678" in u or "3MABR7100075678" in u for u in search_urls[:5])
    # Later queries target transformed MPN
    assert any("7100075678" in u for u in search_urls)


# ==============================================================================
# TEST E: Search Endpoint Failure Falls Back Gracefully
# ==============================================================================


def test_3m_test_e_search_endpoint_failure_falls_back() -> None:
    """When first search template returns 500, fallback template succeeds without crash."""
    failing_search_url = "https://www.3m.com/3M/en_US/search/?q=7100075678"
    fallback_search_url = "https://www.3m.com/3M/en_US/search/?Ntt=7100075678"
    product_url = "https://www.3m.com/3M/en_US/p/d/v000188684"

    fallback_html = (
        b'<html><body><a href="/3M/en_US/p/d/v000188684">'
        b"3M Cubitron II Film Disc 775L Part 7100075678</a></body></html>"
    )
    product_html = (
        b"<html><head><title>3M Cubitron 775L</title></head>"
        b"<body><h1>3M Cubitron II 775L</h1><p>3M Part: 7100075678</p>"
        b"<p>Manufacturer: 3M</p></body></html>"
    )

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        failing_search_url: (500, b"Internal Server Error", {}),
        fallback_search_url: fallback_html,
        product_url: product_html,
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)
    service = ProductSourceDiscoveryService(fetcher)

    product = _make_3m_product()
    profile = ManufacturerProfile(
        manufacturer_id="3m",
        canonical_name="3M",
        verified_domains=("3m.com",),
    )

    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    assert candidates[0].matched_mpn is True
    assert canonicalize_url(candidates[0].url) == canonicalize_url(product_url)
    req_canons = [canonicalize_url(u) for u in pool.requested_urls]
    assert canonicalize_url(failing_search_url) in req_canons
    assert canonicalize_url(fallback_search_url) in req_canons


# ==============================================================================
# TEST F: Client-Shell / JSON-Script Catalog Discovery
# ==============================================================================


def test_3m_test_f_client_shell_json_discovery() -> None:
    """Product URL embedded in JavaScript/JSON state is extracted from search shell."""
    search_url = "https://www.3m.com/3M/en_US/search/?q=7100075678"
    product_url = "https://www.3m.com/3M/en_US/p/d/b40065447"

    # Search page containing JavaScript application state with product link
    shell_html = (
        b'<!DOCTYPE html><html><head><title>Search Results</title>'
        b'<script type="application/json" id="__NEXT_DATA__">'
        b'{"props":{"pageProps":{"results":[{"title":"3M Cubitron II 775L",'
        b'"url":"https://www.3m.com/3M/en_US/p/d/b40065447","sku":"7100075678"}]}}}'
        b"</script></head><body><div id=\"root\"></div></body></html>"
    )
    product_html = (
        b"<html><head><title>3M Cubitron 775L</title></head>"
        b"<body><h1>3M Cubitron II 775L</h1><p>3M Part: 7100075678</p>"
        b"<p>Manufacturer: 3M Company</p></body></html>"
    )

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        search_url: shell_html,
        product_url: product_html,
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)
    service = ProductSourceDiscoveryService(fetcher)

    product = _make_3m_product()
    profile = ManufacturerProfile(
        manufacturer_id="3m",
        canonical_name="3M",
        verified_domains=("3m.com",),
    )

    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    assert candidates[0].matched_mpn is True
    assert "b40065447" in candidates[0].url


# ==============================================================================
# TEST G: Document / Technical Data Sheet Fallback
# ==============================================================================


def test_3m_test_g_document_fallback_recognition() -> None:
    """Links to technical data sheets on multimedia.3m.com are recognized as candidate sources."""
    strat = ThreeMRetrievalStrategy()

    tds_link = DocumentLink(
        url="https://multimedia.3m.com/mws/media/123456/cubitron-775l-tds.pdf",
        anchor_text="3M 775L Technical Data Sheet 7100075678",
    )
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("7100075678", manufacturer_hint="3M")

    assert strat.is_product_link(tds_link, hypotheses, ("3m.com",)) is True


# ==============================================================================
# TEST H: Unverified Third-Party Domain Blocked
# ==============================================================================


def test_3m_test_h_unverified_domain_blocked() -> None:
    """Candidate link pointing to an unverified distributor domain is rejected."""
    policy = SourcePolicy()
    profile = ManufacturerProfile(
        manufacturer_id="3m",
        canonical_name="3M",
        verified_domains=("3m.com",),
    )

    unverified_source = SourceRecord(
        canonical_url="https://unverified-distributor.example/3M/7100075678",
        original_url="https://unverified-distributor.example/3M/7100075678",
        source_kind=SourceKind.DISCOVERY_RESULT,
        decision=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
        manufacturer_id="3m",
        manufacturer_domain="unverified-distributor.example",
    )

    verified = policy.verify_source(unverified_source, profile)
    assert verified.decision != SourceDecision.VERIFIED_MANUFACTURER_SOURCE
    assert policy.allowed_domain(unverified_source.canonical_url, profile) is False


# ==============================================================================
# TEST I: Duplicate Search URL Deduplication
# ==============================================================================


def test_3m_test_i_duplicate_search_deduplicated() -> None:
    """Duplicate search URLs generated across multiple hypotheses are fetched only once."""
    search_url = "https://www.3m.com/3M/en_US/search/?q=7100075678"
    empty_html = b"<html><body><p>No results</p></body></html>"

    routes: dict[str, tuple[int, bytes, dict[str, str]] | bytes] = {
        search_url: empty_html,
    }
    pool = _TrackingHttpPool(routes)
    fetcher = _make_fetcher(pool)
    service = ProductSourceDiscoveryService(fetcher)

    product = _make_3m_product()
    profile = ManufacturerProfile(
        manufacturer_id="3m",
        canonical_name="3M",
        verified_domains=("3m.com",),
    )

    service.discover(product, profile)

    # Count how many times the exact search_url was requested
    canon = canonicalize_url(search_url)
    req_count = sum(1 for u in pool.requested_urls if canonicalize_url(u) == canon)
    assert req_count <= 1
