import pytest

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.truth import Source, SourceAuthority, SourceType
from unilog_product_intelligence.retrieval import (
    EvidenceSelector,
    HtmlParser,
    ManufacturerProfile,
    ProductIdentityMatcher,
    ProductSourceDiscoveryService,
    SafeNetworkTargetResolver,
)
from unilog_product_intelligence.retrieval.core import (
    DocumentChunk,
    FetchResult,
    ParsedDocument,
    RetrievalStatus,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourceRecord,
)


def _source(url: str = "https://acme.com/products/ABC123") -> SourceRecord:
    return SourceRecord(
        canonical_url=url,
        original_url=url,
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="acme",
        manufacturer_domain="acme.com",
        product_id="p-1",
    )


def _product():
    return ProductTruthService().create_from_raw_input(
        "p-1",
        {"Mfg_Part_Num": "ABC123", "Part_Desc": "6 pcs sanding belt", "Part_Manuf": "Acme"},
        Source(
            source_id="input",
            source_type=SourceType.SUPPLIED_INPUT,
            authority=SourceAuthority.HIGH,
        ),
    )


def test_html_parser_removes_pollution_and_preserves_structured_metadata() -> None:
    body = b"""<html><head>
    <title>ABC123 Product</title>
    <link rel="canonical" href="/products/ABC123">
    <script type="application/ld+json">{"@type":"Product","mpn":"ABC123"}</script>
    </head><body><nav>menu noise</nav><main><h1>ABC123</h1>
    <p>6 pcs sanding belt</p><a href="/spec.pdf">Specification Sheet</a>
    </main><footer>cookie noise</footer></body></html>"""
    fetch = FetchResult(source=_source(), body=body, cache_status="cache_miss")

    document = HtmlParser().parse(fetch)
    text = " ".join(chunk.text for chunk in document.chunks)

    assert "6 pcs sanding belt" in text
    assert "menu noise" not in text
    assert "cookie noise" not in text
    assert document.title == "ABC123 Product"
    assert document.canonical_url == "https://acme.com/products/ABC123"
    assert document.structured_metadata["json_ld"][0]["mpn"] == "ABC123"
    assert document.links[0].url == "https://acme.com/spec.pdf"


def test_dns_resolver_rejects_private_resolution() -> None:
    def private_lookup(*args, **kwargs):
        return [(2, 1, 6, "", ("10.0.0.5", 443))]

    resolver = SafeNetworkTargetResolver(lookup=private_lookup)

    with pytest.raises(ValueError, match="private_network_target"):
        resolver.validate("https://manufacturer.example/product")


def test_evidence_selector_prefers_identity_relevant_chunks() -> None:
    document = ParsedDocument(
        source_id="source",
        content_hash="hash",
        parser="html",
        parser_version="v2",
        chunks=[
            DocumentChunk(document_id="d", text="Warranty and shipping information"),
            DocumentChunk(document_id="d", text="ABC123 sanding belt 6 pcs"),
            DocumentChunk(document_id="d", text="Unrelated recommended product"),
        ],
    )

    selected = EvidenceSelector().select(document, {"mpn": "ABC123", "description": "sanding belt"})

    assert selected[0].text == "ABC123 sanding belt 6 pcs"
    assert all("Warranty" not in chunk.text for chunk in selected)


class FakeFetcher:
    def fetch(self, source, refresh=False):
        body = (
            b"<html><title>ABC123 Acme sanding belt</title>"
            b"<main>ABC123 Acme 6 pcs sanding belt</main></html>"
        )
        return FetchResult(
            source=source.model_copy(
                update={"retrieval_status": RetrievalStatus.SUCCESS, "content_type": "text/html"}
            ),
            body=body,
            cache_status="cache_miss",
        )


def test_product_source_discovery_requires_exact_identity_match() -> None:
    candidates = ProductSourceDiscoveryService(FakeFetcher()).discover(
        _product(),
        ManufacturerProfile(
            manufacturer_id="acme",
            canonical_name="Acme",
            verified_domains=("acme.com",),
        ),
        candidate_urls=("https://acme.com/products/ABC123",),
    )

    assert candidates
    assert candidates[0].matched_mpn is True
    assert candidates[0].matched_manufacturer is True
    assert candidates[0].identity_score >= 0.6
    match = ProductIdentityMatcher().match(
        _product(),
        type(
            "Document",
            (),
            {"title": "Related product", "chunks": [type("Chunk", (), {"text": "Acme belt"})()]},
        )(),
    )
    assert match.classification in {"WEAK_MATCH", "MISMATCH"}

class RedirectResponse:
    def __init__(self, status, headers=None, body=b''):
        self.status = status
        self.headers = headers or {}
        self._body = body

    def read(self, limit=-1):
        return self._body

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class AllowResolver:
    def __init__(self):
        self.urls = []

    def validate(self, url):
        self.urls.append(url)


def test_fetcher_follows_only_safe_same_domain_redirects() -> None:
    resolver = AllowResolver()
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            return RedirectResponse(302, {'Location': '/products/ABC123'})
        return RedirectResponse(200, {'Content-Type': 'text/html'}, b'<main>ABC123</main>')

    fetcher = SourceFetcher(resolver=resolver)
    fetcher.opener = opener
    fetcher._custom_opener = False
    result = fetcher.fetch(_source())

    assert result.source.retrieval_status is RetrievalStatus.SUCCESS
    assert result.body == b'<main>ABC123</main>'
    assert calls == ['https://acme.com/products/ABC123', 'https://acme.com/products/ABC123']
    assert resolver.urls == calls


def test_fetcher_rejects_external_redirect() -> None:
    def opener(request, timeout):
        return RedirectResponse(302, {'Location': 'https://evil.example/product'})

    fetcher = SourceFetcher(resolver=AllowResolver())
    fetcher.opener = opener
    fetcher._custom_opener = False
    result = fetcher.fetch(_source())

    assert result.source.retrieval_status is RetrievalStatus.FAILED
    assert result.error == 'redirect_external_domain'