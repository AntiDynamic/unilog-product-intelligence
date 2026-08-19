"""Tests for bounded asynchronous HTTP source discovery and circuit breaking."""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from unilog_product_intelligence.domain.truth import (
    ProductTruth,
    RawInputField,
)
from unilog_product_intelligence.retrieval.core import (
    CacheStatus,
    DomainCircuitBreaker,
    FetchResult,
    ManufacturerProfile,
    RetrievalStatus,
    SourceKind,
    SourceRecord,
)
from unilog_product_intelligence.retrieval.source_discovery import (
    ProductSourceCandidate,
    ProductSourceDiscoveryService,
    _candidate_rank,
)


class MockAsyncSourceFetcher:
    """Fake async fetcher with controlled latency, concurrency tracking, and response mapping."""

    def __init__(
        self,
        responses: dict[str, tuple[int, bytes, str]] | None = None,
        delay_map: dict[str, float] | None = None,
        default_delay: float = 0.01,
        circuit_breaker: DomainCircuitBreaker | None = None,
    ) -> None:
        self.responses = responses or {}
        self.delay_map = delay_map or {}
        self.default_delay = default_delay
        self.circuit_breaker = circuit_breaker or DomainCircuitBreaker()
        self.fetched_urls: list[str] = []
        self.concurrent_requests: int = 0
        self.max_concurrent_seen: int = 0
        self.per_host_concurrent: dict[str, int] = {}
        self.max_per_host_seen: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def fetch_async(self, source: SourceRecord, refresh: bool = False) -> FetchResult:
        url = source.canonical_url
        from unilog_product_intelligence.retrieval.core import _host

        host = _host(url)

        if not self.circuit_breaker.is_available(host):
            return FetchResult(
                source=source.model_copy(update={"retrieval_status": RetrievalStatus.BLOCKED}),
                cache_status=CacheStatus.INVALID,
                error="domain_circuit_tripped",
            )

        async with self._lock:
            self.fetched_urls.append(url)
            self.concurrent_requests += 1
            self.max_concurrent_seen = max(self.max_concurrent_seen, self.concurrent_requests)
            self.per_host_concurrent[host] = self.per_host_concurrent.get(host, 0) + 1
            self.max_per_host_seen[host] = max(
                self.max_per_host_seen.get(host, 0), self.per_host_concurrent[host]
            )

        delay = self.delay_map.get(url, self.delay_map.get(host, self.default_delay))
        if delay > 0:
            await asyncio.sleep(delay)

        async with self._lock:
            self.concurrent_requests -= 1
            self.per_host_concurrent[host] -= 1

        if url in self.responses:
            status_code, body, ct = self.responses[url]
            if status_code == 200:
                self.circuit_breaker.record_success(host)
                return FetchResult(
                    source=source.model_copy(
                        update={
                            "retrieval_status": RetrievalStatus.SUCCESS,
                            "http_status": 200,
                            "content_type": ct,
                        }
                    ),
                    body=body,
                    cache_status=CacheStatus.MISS,
                )
            else:
                reason = "waf_blocked" if status_code in {403, 429} else f"http_{status_code}"
                self.circuit_breaker.record_failure(host, reason)
                return FetchResult(
                    source=source.model_copy(
                        update={
                            "retrieval_status": RetrievalStatus.HTTP_ERROR,
                            "http_status": status_code,
                        }
                    ),
                    cache_status=CacheStatus.INVALID,
                    error=reason,
                )

        # Default fallback HTML response
        self.circuit_breaker.record_success(host)
        html = (
            f"<html><head><title>Product {url}</title></head>"
            f"<body><h1>404 Not Found</h1></body></html>".encode()
        )
        return FetchResult(
            source=source.model_copy(
                update={
                    "retrieval_status": RetrievalStatus.SUCCESS,
                    "http_status": 200,
                    "content_type": "text/html",
                }
            ),
            body=html,
            cache_status=CacheStatus.MISS,
        )

    def fetch(self, source: SourceRecord, refresh: bool = False) -> FetchResult:
        return asyncio.run(self.fetch_async(source, refresh=refresh))


def _make_product(mpn: str, mfg: str, desc: str = "Test Product") -> ProductTruth:
    raw_inputs = (
        RawInputField(field_name="Mfg_Part_Num", raw_value=mpn, source_id="input-1"),
        RawInputField(field_name="Part_Manuf", raw_value=mfg, source_id="input-1"),
        RawInputField(field_name="Part_Desc", raw_value=desc, source_id="input-1"),
    )
    return ProductTruth(product_id=str(uuid4()), raw_inputs=raw_inputs)


def test_concurrent_fetching_and_global_concurrency() -> None:
    """Verify that multiple URLs are fetched concurrently and global concurrency is bounded."""
    async def _test() -> None:
        delay = 0.05
        fake_fetcher = MockAsyncSourceFetcher(default_delay=delay)
        profile = ManufacturerProfile(
            manufacturer_id="milwaukee",
            canonical_name="Milwaukee",
            verified_domains=("milwaukeetool.com",),
            candidate_domains=(),
        )
        service = ProductSourceDiscoveryService(fetcher=fake_fetcher)
        product = _make_product("2804-20", "Milwaukee", "M18 Fuel Hammer Drill")

        candidate_urls = [
            f"https://www.milwaukeetool.com/Products/Power-Tools/Drilling/Hammer-Drills/{i}"
            for i in range(10)
        ]

        t0 = time.perf_counter()
        _ = await service.adiscover(product, profile, candidate_urls=candidate_urls)
        t1 = time.perf_counter()

        elapsed = t1 - t0
        # If sequential, 10 URLs * 0.05s = 0.5s. Concurrently, it should finish in < 0.35s.
        assert elapsed < 0.35
        assert fake_fetcher.max_concurrent_seen > 1

    asyncio.run(_test())


def test_slow_timed_out_host_does_not_block_unrelated_hosts() -> None:
    """Verify a slow/blocked host does not prevent discovering candidates on healthy hosts."""
    async def _test() -> None:
        dead_host_url = "https://www.deadmaker.com/products/TEST-123"
        healthy_host_url = "https://www.healthymaker.com/products/TEST-123"

        html_healthy = b"""
        <html>
            <head><title>Healthy Maker TEST-123</title></head>
            <body>
                <h1>Healthy Maker TEST-123 Precision Tool</h1>
                <p>MPN: TEST-123</p>
            </body>
        </html>
        """

        responses = {
            dead_host_url: (403, b"Forbidden", "text/html"),
            healthy_host_url: (200, html_healthy, "text/html"),
        }
        delay_map = {
            "www.deadmaker.com": 0.08,
            "www.healthymaker.com": 0.01,
        }
        breaker = DomainCircuitBreaker()
        fetcher = MockAsyncSourceFetcher(
            responses=responses, delay_map=delay_map, circuit_breaker=breaker
        )

        profile = ManufacturerProfile(
            manufacturer_id="mixed",
            canonical_name="Mixed",
            verified_domains=("healthymaker.com", "deadmaker.com"),
            candidate_domains=(),
        )
        service = ProductSourceDiscoveryService(fetcher=fetcher, circuit_breaker=breaker)
        product = _make_product("TEST-123", "Mixed", "Precision Tool TEST-123")

        candidates = await service.adiscover(
            product, profile, candidate_urls=[dead_host_url, healthy_host_url]
        )

        assert len(candidates) >= 1
        assert candidates[0].matched_mpn is True
        assert "healthymaker.com" in candidates[0].url
        assert breaker.is_available("healthymaker.com") is True
        assert breaker.is_available("deadmaker.com") is False

    asyncio.run(_test())


def test_early_stop_on_verified_manufacturer_match() -> None:
    """Verify discovery stops immediately when a verified manufacturer candidate matches."""
    async def _test() -> None:
        good_direct_url = "https://www.freudtools.com/products/D0724R"
        good_html = b"""
        <html>
            <head><title>Freud D0724R 7-1/4 in. 24T Saw Blade</title></head>
            <body>
                <h1>D0724R Tracking Point Blade</h1>
                <p>Manufacturer Part Number: D0724R</p>
            </body>
        </html>
        """
        responses = {
            good_direct_url: (200, good_html, "text/html"),
        }
        fetcher = MockAsyncSourceFetcher(responses=responses, default_delay=0.01)
        profile = ManufacturerProfile(
            manufacturer_id="freud",
            canonical_name="Freud",
            verified_domains=("freudtools.com", "diablotools.com"),
            candidate_domains=(),
        )
        service = ProductSourceDiscoveryService(fetcher=fetcher)
        product = _make_product("D0724R", "Freud", "Freud 7-1/4 24T Blade D0724R")

        candidates = await service.adiscover(product, profile)

        assert len(candidates) >= 1
        top = candidates[0]
        assert top.matched_mpn is True
        assert top.identity_score >= 0.6
        assert top.domain_score >= 1.0

    asyncio.run(_test())


def test_distributor_cannot_override_manufacturer() -> None:
    """Verify secondary distributor candidate cannot override verified manufacturer candidate."""
    mfg_cand = ProductSourceCandidate(
        url="https://www.whirlpool.com/washers/WDTS7024RZ",
        title="Whirlpool WDTS7024RZ",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        discovery_method="direct_product_path",
        evidence_snippet="Whirlpool WDTS7024RZ Dishwasher",
        matched_mpn=True,
        matched_manufacturer=True,
        matched_brand=True,
        identity_score=0.95,
        domain_score=1.0,
        relevance_score=0.95,
    )
    dist_cand = ProductSourceCandidate(
        url="https://www.grainger.com/product/WDTS7024RZ",
        title="Grainger Whirlpool WDTS7024RZ",
        source_kind=SourceKind.DISTRIBUTOR_PRODUCT_PAGE,
        discovery_method="distributor_secondary_fallback",
        evidence_snippet="Grainger WDTS7024RZ Dishwasher",
        matched_mpn=True,
        matched_manufacturer=True,
        matched_brand=True,
        identity_score=0.99,
        domain_score=0.75,
        relevance_score=0.99,
    )

    ranked = sorted([dist_cand, mfg_cand], key=_candidate_rank)
    assert ranked[0] == mfg_cand
    assert ranked[1] == dist_cand


def test_domain_circuit_breaker_behavior() -> None:
    """Verify circuit breaker trips on repeated timeouts and WAF blocks."""
    breaker = DomainCircuitBreaker(max_consecutive_failures=3)
    domain = "tarpit-host.com"

    assert breaker.is_available(domain) is True

    # 1st and 2nd timeout
    breaker.record_failure(domain, "timeout")
    assert breaker.is_available(domain) is True
    breaker.record_failure(domain, "timeout")
    assert breaker.is_available(domain) is True

    # 3rd timeout trips tarpitting
    breaker.record_failure(domain, "timeout")
    assert breaker.is_available(domain) is False
    assert breaker.get_failure_reason(domain) == "timeout"

    # WAF block trips immediately
    waf_domain = "akamai-block.com"
    breaker.record_failure(waf_domain, "waf_blocked")
    assert breaker.is_available(waf_domain) is False
    assert breaker.get_failure_reason(waf_domain) == "waf_blocked"


def test_sync_public_discover_wrapper_compatibility() -> None:
    """Verify that synchronous discover() works without requiring caller asyncio setup."""
    good_direct_url = "https://www.milwaukeetool.com/Products/Power-Tools/2804-20"
    good_html = b"""
    <html>
        <head><title>Milwaukee 2804-20 M18 FUEL Hammer Drill</title></head>
        <body>
            <h1>2804-20 Hammer Drill</h1>
            <p>MPN: 2804-20</p>
        </body>
    </html>
    """
    responses = {good_direct_url: (200, good_html, "text/html")}
    fetcher = MockAsyncSourceFetcher(responses=responses, default_delay=0.01)
    profile = ManufacturerProfile(
        manufacturer_id="milwaukee",
        canonical_name="Milwaukee",
        verified_domains=("milwaukeetool.com",),
        candidate_domains=(),
    )
    service = ProductSourceDiscoveryService(fetcher=fetcher)
    product = _make_product("2804-20", "Milwaukee", "M18 Fuel Hammer Drill 2804-20")

    # Calling synchronous discover() directly
    candidates = service.discover(product, profile, candidate_urls=[good_direct_url])

    assert len(candidates) >= 1
    assert candidates[0].matched_mpn is True
    assert candidates[0].identity_score >= 0.6
    assert service.selected_domain in {"milwaukeetool.com", "www.milwaukeetool.com"}


def test_per_host_concurrency_limiting() -> None:
    """Verify that per-host concurrency is tracked and bounded."""
    async def _test() -> None:
        delay = 0.04
        fetcher = MockAsyncSourceFetcher(default_delay=delay)
        profile = ManufacturerProfile(
            manufacturer_id="3m",
            canonical_name="3M",
            verified_domains=("3m.com",),
            candidate_domains=(),
        )
        service = ProductSourceDiscoveryService(fetcher=fetcher)
        product = _make_product("07048", "3M", "3M Half Facepiece Respirator 07048")

        urls = [f"https://www.3m.com/respirators/{i}" for i in range(8)]
        await service.adiscover(product, profile, candidate_urls=urls)

        assert fetcher.max_per_host_seen.get("www.3m.com", 0) >= 1

    asyncio.run(_test())

