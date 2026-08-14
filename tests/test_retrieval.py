from datetime import timedelta

import pytest

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.truth import Source, SourceAuthority, SourceType
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.retrieval import (
    EvidenceExtractor,
    HtmlParser,
    ManufacturerIntelligenceService,
    ManufacturerProfile,
    SourceCache,
    SourceFetcher,
    SourcePolicy,
    SourceRecord,
    SourceVerifier,
    canonicalize_url,
)
from unilog_product_intelligence.retrieval.core import (
    CacheStatus,
    RetrievalStatus,
    SourceDecision,
    SourceKind,
)


class FakeResponse:
    status = 200
    headers = {"Content-Type": "text/html", "ETag": '"v1"'}

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class FakeProvider(LLMProvider):
    def generate(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("URL Context path should be used")

    def generate_with_tools(
        self, request: LLMRequest, tools: list[dict[str, object]]
    ) -> LLMResponse:
        assert tools == [{"type": "url_context"}]
        return LLMResponse(
            output_text='{"candidates":[{"attribute":"quantity","raw_value":"6 pcs","normalized_candidate":"6","unit":"pcs","source_id":"ignored","url":"ignored","source_text":"6 pcs","evidence_type":"direct","status":"direct"}],"unresolved_attributes":[]}',  # noqa: E501
            model="test",
            input_tokens=10,
            output_tokens=8,
        )


def test_url_canonicalization_removes_tracking_and_fragment() -> None:
    assert (
        canonicalize_url("HTTPS://Example.COM:443/a/?utm_source=x#section")
        == "https://example.com/a"
    )


def test_source_policy_rejects_marketplaces_and_keeps_unknown_domains_as_candidates() -> None:
    policy = SourcePolicy()
    profile = ManufacturerProfile(
        manufacturer_id="m-1", canonical_name="Acme", verified_domains=("acme.com",)
    )
    blocked = SourceRecord(
        canonical_url="https://amazon.com/p/ABC",
        original_url="https://amazon.com/p/ABC",
        source_kind=SourceKind.DISCOVERY_RESULT,
        decision=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
        manufacturer_id="m-1",
        manufacturer_domain="amazon.com",
    )
    assert policy.verify_source(blocked, profile).decision == SourceDecision.NON_AUTHORITATIVE
    unknown = SourceRecord(
        canonical_url="https://docs.acme.com/p/ABC",
        original_url="https://docs.acme.com/p/ABC",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
        manufacturer_id="m-1",
        manufacturer_domain="docs.acme.com",
    )
    assert (
        SourceVerifier().verify_source(unknown, profile).decision
        == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
    )


def test_fetch_is_bounded_and_cached() -> None:
    body = b"<html><title>ABC123</title><p>ABC123 6 pcs</p></html>"
    calls = 0

    def opener(request: object, timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse(body)

    source = SourceRecord(
        canonical_url="https://acme.com/p/ABC123",
        original_url="https://acme.com/p/ABC123",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="m-1",
        manufacturer_domain="acme.com",
    )
    fetcher = SourceFetcher(
        cache=SourceCache(timedelta(hours=1)), opener=opener, requests_per_second=1000
    )
    first = fetcher.fetch(source)
    second = fetcher.fetch(source)
    assert first.cache_status == CacheStatus.MISS
    assert second.cache_status == CacheStatus.HIT
    assert calls == 1


def test_html_parser_preserves_source_location() -> None:
    source = SourceRecord(
        canonical_url="https://acme.com/p/ABC123",
        original_url="https://acme.com/p/ABC123",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="m-1",
        manufacturer_domain="acme.com",
    )
    fetcher = SourceFetcher(
        opener=lambda request, timeout: FakeResponse(b"<title>ABC123</title><p>6 pcs</p>"),
        requests_per_second=1000,
    )
    document = HtmlParser().parse(fetcher.fetch(source))
    assert "6 pcs" in document.chunks[0].text
    assert document.chunks[0].location["url"] == source.canonical_url


def test_manufacturer_service_attaches_evidence_without_verifying_it_as_truth() -> None:
    truth = ProductTruthService()
    product = truth.create_from_raw_input(
        "p-1",
        {"Mfg_Part_Num": "ABC123", "Part_Desc": "6 pcs"},
        Source(
            source_id="input", source_type=SourceType.SUPPLIED_INPUT, authority=SourceAuthority.HIGH
        ),
    )
    product = truth.add_classification(product, {})
    source = SourceRecord(
        canonical_url="https://acme.com/p/ABC123",
        original_url="https://acme.com/p/ABC123",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="m-1",
        manufacturer_domain="acme.com",
    )
    fetcher = SourceFetcher(
        opener=lambda request, timeout: FakeResponse(b"<title>ABC123</title><p>ABC123 6 pcs</p>"),
        requests_per_second=1000,
    )
    product, job = ManufacturerIntelligenceService(
        fetcher, extractor=EvidenceExtractor(FakeProvider())
    ).process(
        product,
        source,
        ManufacturerProfile(
            manufacturer_id="m-1", canonical_name="Acme", verified_domains=("acme.com",)
        ),
    )
    assert job.state.value == "completed"
    assert product.sources[-1].authority == SourceAuthority.AUTHORITATIVE
    assert product.attribute("attribute-quantity").candidates[0].status.value == "candidate"
    assert product.evidence[0].quoted_text == "6 pcs"


def test_private_urls_are_rejected_before_fetch() -> None:
    with pytest.raises(ValueError, match="private"):
        canonicalize_url("http://127.0.0.1/private")


def test_unsupported_content_type_is_not_cached() -> None:
    class BinaryResponse(FakeResponse):
        headers = {"Content-Type": "application/octet-stream"}

    source = SourceRecord(
        canonical_url="https://acme.com/p/ABC123",
        original_url="https://acme.com/p/ABC123",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="m-1",
        manufacturer_domain="acme.com",
    )
    result = SourceFetcher(
        opener=lambda request, timeout: BinaryResponse(b"binary"),
        requests_per_second=1000,
    ).fetch(source)
    assert result.source.retrieval_status == RetrievalStatus.INVALID_CONTENT_TYPE
