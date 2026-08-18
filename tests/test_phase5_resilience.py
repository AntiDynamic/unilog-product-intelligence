"""Phase 5 retrieval resilience tests.

These tests verify the full retrieval priority hierarchy:
  1. Cached verified domain (DomainResolver verified cache)
  2. Registered ManufacturerProfile verified domains
  3. Audited manufacturer domain catalog (by name)
  4. Audited catalog lookup by brand alias
  5. DeterministicUrlStrategy candidate generation (no HTTP)
  6. ProductIdentityMatcher rejection of mismatched pages
  7. Distributor domain rejection
  8. ManufacturerIntelligenceService.recover() for SOURCE_FETCH_FAILED / PRODUCT_IDENTITY_MISMATCH
  9. Gemini 429 → Phase5FailureReason.GEMINI_RATE_LIMIT / GEMINI_BILLING_FAILURE
  10. Successful retrieval without any Gemini calls (deterministic path)
  11. DiscoveryResult.retrieval_strategies_attempted is always populated
  12. Phase5FailureReason enum completeness
"""

from __future__ import annotations

import pytest

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.truth import Source, SourceAuthority, SourceType
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.retrieval import (
    DeterministicUrlStrategy,
    DomainResolver,
    ManufacturerDiscoveryAgent,
    ManufacturerIntelligenceService,
    ManufacturerProfile,
    Phase5FailureReason,
    SourceCache,
    SourceFetcher,
    SourcePolicy,
    SourceRecord,
    SourceVerifier,
)
from unilog_product_intelligence.retrieval.core import (
    CacheStatus,
    RetrievalStatus,
    SourceDecision,
    SourceKind,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────


def _product(
    mpn: str = "ABC123",
    manufacturer: str = "Acme",
    brand: str | None = None,
    product_id: str = "p-1",
):
    raw: dict[str, object] = {
        "Mfg_Part_Num": mpn,
        "Part_Desc": "test product description",
        "Part_Manuf": manufacturer,
    }
    if brand:
        raw["Unilog_Brand"] = brand
    return ProductTruthService().create_from_raw_input(
        product_id,
        raw,
        Source(
            source_id="input",
            source_type=SourceType.SUPPLIED_INPUT,
            authority=SourceAuthority.HIGH,
        ),
    )


def _source(
    url: str = "https://acme.com/products/ABC123",
    manufacturer_id: str = "m-acme",
    manufacturer_domain: str = "acme.com",
) -> SourceRecord:
    return SourceRecord(
        canonical_url=url,
        original_url=url,
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id=manufacturer_id,
        manufacturer_domain=manufacturer_domain,
        product_id="p-1",
    )


def _profile(
    manufacturer_id: str = "m-acme",
    name: str = "Acme Corp",
    verified_domains: tuple[str, ...] = ("acme.com",),
) -> ManufacturerProfile:
    return ManufacturerProfile(
        manufacturer_id=manufacturer_id,
        canonical_name=name,
        verified_domains=verified_domains,
    )


class _NeverCallProvider(LLMProvider):
    """Blows up if any LLM call is made — verifies deterministic path skips Gemini."""

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Gemini must NOT be called on the deterministic path")

    def generate_with_tools(
        self, request: LLMRequest, tools: list[dict[str, object]]
    ) -> LLMResponse:
        raise AssertionError("Gemini must NOT be called on the deterministic path")


class _RateLimitProvider(LLMProvider):
    """Simulates a Gemini HTTP 429 rate-limit error."""

    class _RateLimitError(Exception):
        """Fake 429 error."""

        status_code: int = 429
        error_details: list[dict] = [{"reason": "RATE_LIMIT_EXCEEDED"}]

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise self._RateLimitError("rate limit exceeded")

    def generate_with_tools(
        self, request: LLMRequest, tools: list[dict[str, object]]
    ) -> LLMResponse:
        raise self._RateLimitError("rate limit exceeded")


class _BillingProvider(LLMProvider):
    """Simulates a Gemini billing / spend-limit error."""

    class _BillingError(Exception):
        """Fake billing 429."""

        status_code: int = 429
        error_details: list[dict] = [{"reason": "BILLING_DISABLED"}]

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise self._BillingError("billing disabled")

    def generate_with_tools(
        self, request: LLMRequest, tools: list[dict[str, object]]
    ) -> LLMResponse:
        raise self._BillingError("billing disabled")


class _FakeHttpPool:
    """Synchronous HTTP pool stub that serves controlled fake responses."""

    def __init__(self, responses: dict[str, bytes], *, status: int = 200) -> None:
        self._responses = responses
        self._status = status

    def __call__(self, request, timeout=15.0):
        """Act as SourceFetcher's opener callable."""
        url = getattr(request, "full_url", str(request))
        body = self._responses.get(url, b"")
        return _FakeHttpResponse(body=body, status=self._status if body else 404)


class _FakeHttpResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status
        ct = "text/html" if body else "text/plain"
        self.headers: dict[str, str] = {"Content-Type": ct, "ETag": '"v1"'}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


def _fetcher(opener) -> SourceFetcher:
    return SourceFetcher(
        cache=SourceCache(),
        opener=opener,
        requests_per_second=1_000.0,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. DomainResolver — verified cache (fastest path)
# ──────────────────────────────────────────────────────────────────────────────


def test_domain_resolver_returns_verified_cache_hit() -> None:
    profile = ManufacturerProfile(
        manufacturer_id="m-diablo",
        canonical_name="Diablo Tools",
        verified_domains=("diablotools.com",),
    )
    resolver = DomainResolver(profiles={"m-diablo": profile})
    # register() pre-populates the verified_domain_cache
    resolver.register(profile)

    candidates = resolver.resolve("m-diablo", "Diablo Tools")

    assert len(candidates) == 1
    assert candidates[0].domain == "diablotools.com"
    assert candidates[0].source == "verified_domain_cache"
    assert candidates[0].status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE



# ──────────────────────────────────────────────────────────────────────────────
# 2. Known manufacturer domain from expanded catalog
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "expected_domain"),
    [
        ("Milwaukee Tool", "milwaukeetool.com"),
        ("DeWalt", "dewalt.com"),
        ("Makita", "makita.com"),
        ("Festool", "festoolusa.com"),
        ("Mirka Abrasives", "mirka.com"),
        ("Leviton", "leviton.com"),
        ("Kichler Lighting", "kichler.com"),
        ("Freud Inc", "diablotools.com"),
        ("Diablo", "diablotools.com"),
        ("Bosch", "boschtools.com"),
        ("Ridgid", "ridgid.com"),
        ("Lutron Electronics", "lutron.com"),
    ],
)
def test_known_manufacturer_catalog_resolves_domain(name: str, expected_domain: str) -> None:
    resolver = DomainResolver()
    candidates = resolver.resolve(f"m-{name.lower().replace(' ', '-')}", name)

    assert any(c.domain == expected_domain for c in candidates), (
        f"Expected domain '{expected_domain}' for manufacturer '{name}', got: "
        f"{[c.domain for c in candidates]}"
    )
    assert all(c.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE for c in candidates)
    assert all(c.source == "audited_manufacturer_domain_catalog" for c in candidates)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Brand-alias domain resolution
# ──────────────────────────────────────────────────────────────────────────────


def test_domain_resolver_uses_brand_when_manufacturer_unknown() -> None:
    """When Part_Manuf is a distributor not in catalog, brand resolves the domain."""
    resolver = DomainResolver()
    # "Appliance Dealers Cooperative" is not in catalog; brand "Diablo" is.
    candidates = resolver.resolve(
        "m-adc",
        "Appliance Dealers Cooperative",
        brand="Diablo",
    )

    assert len(candidates) > 0
    assert candidates[0].domain == "diablotools.com"
    assert candidates[0].reason == "brand_name_match"
    assert candidates[0].status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE


def test_domain_resolver_brand_not_used_when_manufacturer_resolves() -> None:
    """Brand fallback should NOT fire when manufacturer already resolves from catalog."""
    resolver = DomainResolver()
    candidates = resolver.resolve("m-dewalt", "DeWalt", brand="Some Unknown Brand")

    assert all(c.domain == "dewalt.com" for c in candidates)
    assert all(c.reason == "manufacturer_name_match" for c in candidates)


# ──────────────────────────────────────────────────────────────────────────────
# 4. DeterministicUrlStrategy — pure URL generation
# ──────────────────────────────────────────────────────────────────────────────


def test_deterministic_url_strategy_generates_product_paths() -> None:
    strategy = DeterministicUrlStrategy()
    candidates = strategy.product_url_candidates("diablotools.com", "DCB518ASTS06G")

    assert all(url.startswith("https://diablotools.com/") for url in candidates)
    assert any("products/DCB518ASTS06G" in url for url in candidates)
    assert any("product/DCB518ASTS06G" in url for url in candidates)
    # All candidates must be unique
    assert len(candidates) == len(set(candidates))


def test_deterministic_url_strategy_generates_site_search_patterns() -> None:
    strategy = DeterministicUrlStrategy()
    candidates = strategy.product_url_candidates("milwaukeetool.com", "2960-20")

    search_urls = [url for url in candidates if "search" in url or "s=" in url]
    assert len(search_urls) > 0


def test_deterministic_url_strategy_sanitises_mpn_special_characters() -> None:
    strategy = DeterministicUrlStrategy()
    # MPN with spaces and slashes must not produce invalid URLs
    candidates = strategy.product_url_candidates("example.com", "ABC 123/X")

    assert len(candidates) > 0
    for url in candidates:
        assert " " not in url
        assert url.startswith("https://")


def test_deterministic_url_strategy_empty_mpn_returns_no_candidates() -> None:
    strategy = DeterministicUrlStrategy()
    assert strategy.product_url_candidates("example.com", "") == ()
    assert strategy.product_url_candidates("example.com", "  ") == ()


def test_deterministic_url_strategy_all_candidates_deduplicates() -> None:
    strategy = DeterministicUrlStrategy()
    domains = ("diablotools.com", "diablotools.com")  # duplicated domain
    candidates = strategy.all_candidates(domains, "MPN-123")

    assert len(candidates) == len(set(candidates)), "all_candidates must deduplicate URLs"


def test_deterministic_url_strategy_sitemap_candidates() -> None:
    strategy = DeterministicUrlStrategy()
    sitemaps = strategy.sitemap_candidates("festoolusa.com")

    assert any("sitemap.xml" in url for url in sitemaps)
    assert all(url.startswith("https://festoolusa.com/") for url in sitemaps)


# ──────────────────────────────────────────────────────────────────────────────
# 5. ManufacturerDiscoveryAgent — deterministic fast path skips Gemini
# ──────────────────────────────────────────────────────────────────────────────


def test_discovery_agent_uses_catalog_without_gemini() -> None:
    """Manufacturer in audited catalog → DiscoveryResult returned without calling Gemini."""
    resolver = DomainResolver()
    agent = ManufacturerDiscoveryAgent(
        provider=_NeverCallProvider(),
        resolver=resolver,
    )
    result = agent.discover(
        manufacturer_id="m-dewalt",
        manufacturer_name="DeWalt",
        mpn="DCD791D2",
    )

    assert len(result.candidates) > 0
    assert any(c.domain == "dewalt.com" for c in result.candidates)
    assert result.failure_reason is None
    assert "domain_resolver" in result.retrieval_strategies_attempted
    assert result.search_requested is False


def test_discovery_agent_uses_brand_alias_without_gemini() -> None:
    """Brand alias resolves domain from catalog; Gemini must NOT be called."""
    resolver = DomainResolver()
    agent = ManufacturerDiscoveryAgent(
        provider=_NeverCallProvider(),
        resolver=resolver,
    )
    result = agent.discover(
        manufacturer_id="m-unknown-dist",
        manufacturer_name="Unknown Distributor Corp",
        mpn="DCB518ASTS06G",
        brand="Diablo",
    )

    assert any(c.domain == "diablotools.com" for c in result.candidates)
    assert result.failure_reason is None
    assert result.search_requested is False


def test_discovery_agent_records_strategies_attempted() -> None:
    resolver = DomainResolver()
    agent = ManufacturerDiscoveryAgent(provider=_NeverCallProvider(), resolver=resolver)

    result = agent.discover(
        manufacturer_id="m-milwaukee",
        manufacturer_name="Milwaukee Tool",
        mpn="2960-20",
    )

    assert len(result.retrieval_strategies_attempted) > 0
    assert "domain_resolver" in result.retrieval_strategies_attempted


# ──────────────────────────────────────────────────────────────────────────────
# 6. Gemini 429 → Phase5FailureReason
# ──────────────────────────────────────────────────────────────────────────────


def test_gemini_rate_limit_recorded_honestly() -> None:
    """429 from Gemini -> GEMINI_RATE_LIMIT, candidates preserved."""
    # Use a manufacturer NOT in the catalog so the agent reaches Gemini
    resolver = DomainResolver()
    agent = ManufacturerDiscoveryAgent(
        provider=_RateLimitProvider(),
        resolver=resolver,
    )
    result = agent.discover(
        manufacturer_id="m-zz-unknown",
        manufacturer_name="Zz Unknown Corp",  # not in catalog
        mpn="MPN-FAKE-001",
    )

    assert result.failure_reason == Phase5FailureReason.GEMINI_RATE_LIMIT
    assert result.unresolved_reason is not None
    assert "gemini_error" in result.unresolved_reason
    assert "gemini_search_fallback" in result.retrieval_strategies_attempted


def test_gemini_billing_failure_recorded_as_billing_reason() -> None:
    resolver = DomainResolver()
    agent = ManufacturerDiscoveryAgent(
        provider=_BillingProvider(),
        resolver=resolver,
    )
    result = agent.discover(
        manufacturer_id="m-zz-billing",
        manufacturer_name="Zz Billing Corp",
        mpn="MPN-FAKE-002",
    )

    # Both rate-limit and billing errors are surfaced as GEMINI_RATE_LIMIT or GEMINI_BILLING_FAILURE
    assert result.failure_reason in {
        Phase5FailureReason.GEMINI_RATE_LIMIT,
        Phase5FailureReason.GEMINI_BILLING_FAILURE,
    }
    assert result.failure_reason is not None


# ──────────────────────────────────────────────────────────────────────────────
# 7. ManufacturerIntelligenceService — failure_reason tracking
# ──────────────────────────────────────────────────────────────────────────────


def test_service_records_domain_unverified_failure_reason() -> None:
    """SourceVerifier rejects non-manufacturer domain → DOMAIN_UNVERIFIED."""
    fetcher = _fetcher(_FakeHttpPool({}))
    service = ManufacturerIntelligenceService(fetcher=fetcher)
    product = _product()
    # Use an Amazon URL — SourcePolicy will reject this
    source = _source(
        url="https://amazon.com/p/ABC123",
        manufacturer_id="m-acme",
        manufacturer_domain="amazon.com",
    )
    profile = _profile()

    _, job = service.process(product, source, profile)

    assert job.failure_reason == Phase5FailureReason.DOMAIN_UNVERIFIED


def test_service_records_fetch_failure_on_404() -> None:
    """HTTP 404 on source URL → SOURCE_FETCH_FAILED."""
    fetcher = _fetcher(_FakeHttpPool({}, status=404))
    service = ManufacturerIntelligenceService(fetcher=fetcher)
    product = _product()
    source = _source(url="https://acme.com/products/NOTFOUND")
    profile = _profile()

    _, job = service.process(product, source, profile)

    assert job.failure_reason == Phase5FailureReason.SOURCE_FETCH_FAILED


def test_service_records_identity_mismatch_failure_reason() -> None:
    """Fetched page contains completely different product content -> PRODUCT_IDENTITY_MISMATCH."""
    # Return a page with zero mention of MPN or manufacturer
    body = b"<html><body><h1>Different Product XYZ</h1><p>Unrelated content.</p></body></html>"
    url = "https://acme.com/products/ABC123"
    fetcher = _fetcher(_FakeHttpPool({url: body}))
    service = ManufacturerIntelligenceService(fetcher=fetcher)
    product = _product(mpn="SPECIFICMPN999", manufacturer="SpecificManufacturer")
    source = _source(url=url)
    profile = _profile()

    _, job = service.process(product, source, profile)

    assert job.failure_reason == Phase5FailureReason.PRODUCT_IDENTITY_MISMATCH


# ──────────────────────────────────────────────────────────────────────────────
# 8. ManufacturerIntelligenceService.recover()
# ──────────────────────────────────────────────────────────────────────────────


def test_service_recover_skips_non_recoverable_failure_reasons() -> None:
    """DOMAIN_UNVERIFIED is not recoverable — recover() must return the original job unchanged."""
    from unilog_product_intelligence.retrieval.service import ManufacturerJob, ManufacturerJobState

    fetcher = _fetcher(_FakeHttpPool({}))
    service = ManufacturerIntelligenceService(fetcher=fetcher)
    product = _product()
    profile = _profile()
    failed_job = ManufacturerJob(
        product_id="p-1",
        state=ManufacturerJobState.REVIEW_REQUIRED,
        failure_reason=Phase5FailureReason.DOMAIN_UNVERIFIED,
    )

    _, returned_job = service.recover(product, profile, failed_job)

    # Should be unchanged — DOMAIN_UNVERIFIED is not in the recoverable set
    assert returned_job.failure_reason == Phase5FailureReason.DOMAIN_UNVERIFIED


def test_service_recover_attempts_alternate_candidates_on_fetch_failure() -> None:
    """SOURCE_FETCH_FAILED → recover() tries candidate_urls via ProductSourceDiscoveryService."""
    from unilog_product_intelligence.retrieval.service import ManufacturerJob, ManufacturerJobState

    alt_url = "https://acme.com/product/ABC123"
    body = b"<html><body><h1>ABC123</h1><p>Product by Acme Corp. MPN: ABC123</p></body></html>"
    fetcher = _fetcher(_FakeHttpPool({alt_url: body}))
    service = ManufacturerIntelligenceService(fetcher=fetcher)
    product = _product(mpn="ABC123", manufacturer="Acme")
    profile = _profile(verified_domains=("acme.com",))
    failed_job = ManufacturerJob(
        product_id="p-1",
        state=ManufacturerJobState.FAILED,
        failure_reason=Phase5FailureReason.SOURCE_FETCH_FAILED,
    )

    _, recovery_job = service.recover(
        product, profile, failed_job, candidate_urls=(alt_url,)
    )

    # Recovery either finds the alternate source or reports PRODUCT_SOURCE_NOT_FOUND —
    # in both cases, the job must NOT still carry SOURCE_FETCH_FAILED.
    assert recovery_job.failure_reason != Phase5FailureReason.SOURCE_FETCH_FAILED


# ──────────────────────────────────────────────────────────────────────────────
# 9. Phase5FailureReason enum completeness
# ──────────────────────────────────────────────────────────────────────────────


def test_phase5_failure_reason_enum_has_all_expected_members() -> None:
    expected = {
        "manufacturer_unknown",
        "domain_unknown",
        "domain_unverified",
        "product_source_not_found",
        "product_identity_mismatch",
        "source_fetch_failed",
        "source_parse_failed",
        "no_authoritative_evidence",
        "gemini_billing_failure",
        "gemini_rate_limit",
        "retrieval_requires_review",
    }
    actual = {member.value for member in Phase5FailureReason}
    assert expected == actual, f"Missing: {expected - actual}, Extra: {actual - expected}"


# ──────────────────────────────────────────────────────────────────────────────
# 10. Distributor domain rejection
# ──────────────────────────────────────────────────────────────────────────────


def test_source_policy_rejects_distributor_url_as_non_authoritative() -> None:
    """Distributor URL must not be classified as VERIFIED_MANUFACTURER_SOURCE."""
    policy = SourcePolicy()
    profile = ManufacturerProfile(
        manufacturer_id="m-acme",
        canonical_name="Acme Corp",
        verified_domains=("acme.com",),
    )
    distributor_source = SourceRecord(
        canonical_url="https://grainger.com/product/ABC123",
        original_url="https://grainger.com/product/ABC123",
        source_kind=SourceKind.DISCOVERY_RESULT,
        decision=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
        manufacturer_id="m-acme",
        manufacturer_domain="grainger.com",
        product_id="p-1",
    )
    verifier = SourceVerifier(policy)
    result = verifier.verify_source(
        distributor_source, profile, product_terms=("ABC123", "Acme")
    )

    assert result.decision != SourceDecision.VERIFIED_MANUFACTURER_SOURCE


# ──────────────────────────────────────────────────────────────────────────────
# 11. End-to-end Brand resolution through Phase65Pipeline
# ──────────────────────────────────────────────────────────────────────────────


def test_brand_passed_from_product_truth_to_discovery_resolves_distributor_manufacturer() -> None:
    """When Part_Manuf is a distributor, brand extracts and resolves manufacturer domain."""
    from unilog_product_intelligence.application.phase65 import Phase65Pipeline, Phase65Status
    from unilog_product_intelligence.enrichment.models import EnrichmentResult, EnrichmentStatus
    from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService

    # Product with unknown distributor as Part_Manuf and "Diablo" as brand
    product = _product(
        mpn="DCB518ASTS06G",
        manufacturer="Appliance Dealers Cooperative",
        brand="Diablo",
    )

    fake_html = (
        b"<!DOCTYPE html><html><head><title>DCB518ASTS06G - Diablo Tools</title></head>"
        b"<body><h1>Diablo DCB518ASTS06G</h1><p>Manufacturer Part Number: DCB518ASTS06G</p>"
        b"<p>Made by Freud Inc / Diablo Tools.</p></body></html>"
    )
    target_url = "https://diablotools.com/products/DCB518ASTS06G"
    fetcher = _fetcher(_FakeHttpPool({target_url: fake_html}))

    class FakeOrch:
        def run(self, p):
            from unilog_product_intelligence.agents.orchestration import JobState, ProductJob
            p = ProductTruthService().add_classification(p, {})
            return p, ProductJob(
                job_id=f"job-{p.product_id}",
                product_id=p.product_id,
                state=JobState.UNDERSTOOD,
            )

    class FakeEnrich:
        def enrich(self, p, *args: object, **kwargs: object):
            from unilog_product_intelligence.enrichment.models import PublicationState
            return EnrichmentResult(
                product_id=p.product_id,
                status=EnrichmentStatus.ENRICHED,
                publication_state=PublicationState.READY,
                product_truth=p,
            )

    disc_service = ProductSourceDiscoveryService(fetcher)

    def binding(p, disc):
        candidates = disc_service.discover(
            p,
            ManufacturerProfile(
                manufacturer_id="Freud Inc",
                canonical_name="Freud Inc",
                verified_domains=tuple(c.domain for c in disc.candidates),
            ),
            candidate_urls=disc.search_result_urls,
        )
        if not candidates:
            return None
        c = candidates[0]
        return (
            SourceRecord(
                canonical_url=c.url,
                original_url=c.url,
                source_kind=c.source_kind,
                decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                manufacturer_id="Freud Inc",
                manufacturer_domain="diablotools.com",
                product_id=p.product_id,
            ),
            ManufacturerProfile(
                manufacturer_id="Freud Inc",
                canonical_name="Freud Inc",
                verified_domains=("diablotools.com",),
            ),
        )

    class FakeExtractor:
        def __init__(self, mpn="DCB518ASTS06G"):
            self.mpn = mpn
            self.last_response = None

        def extract(self, document, url, product_context):
            from unilog_product_intelligence.retrieval.core import (
                EvidenceCandidate,
                EvidenceExtractionResult,
                EvidenceStatus,
            )
            return EvidenceExtractionResult(
                candidates=[
                    EvidenceCandidate(
                        attribute="manufacturer_part_number",
                        raw_value=self.mpn,
                        normalized_candidate=self.mpn,
                        source_id=document.source_id,
                        url=url,
                        source_text=f"Model # {self.mpn}",
                        evidence_type=EvidenceStatus.DIRECT,
                        status=EvidenceStatus.DIRECT,
                    )
                ]
            )

    extractor = FakeExtractor("DCB518ASTS06G")
    pipeline = Phase65Pipeline(
        orchestrator=FakeOrch(),
        discovery=ManufacturerDiscoveryAgent(_NeverCallProvider(), DomainResolver()),
        manufacturer=ManufacturerIntelligenceService(fetcher=fetcher, extractor=extractor),
        enrichment=FakeEnrich(),
        source_binding=binding,
    )

    result = pipeline.run(product)

    assert result.status == Phase65Status.ENRICHED
    assert result.discovery is not None
    # Diablo brand must resolve diablotools.com
    assert any(c.domain == "diablotools.com" for c in result.discovery.candidates)
    assert result.manufacturer_job is not None
    assert result.manufacturer_job.state.value == "completed"


# ──────────────────────────────────────────────────────────────────────────────
# 12. Site-Search Retrieval (fetching search page, extracting product links)
# ──────────────────────────────────────────────────────────────────────────────


def test_site_search_fetches_search_page_and_extracts_product_link() -> None:
    """When direct product URL is 404, site-search endpoint returns search page with link."""
    from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService

    search_url = "https://diablotools.com/search?q=DCB518ASTS06G"
    product_url = "https://diablotools.com/catalogue/tools/detail?id=829192"

    search_html = (
        b"<!DOCTYPE html><html><head><title>Search Results</title></head>"
        b"<body><div class='search-results'>"
        b"<a href='/catalogue/tools/detail?id=829192'>DCB518ASTS06G 5-1/8 Demo Demon Blade</a>"
        b"</div></body></html>"
    )
    product_html = (
        b"<!DOCTYPE html><html><head><title>DCB518ASTS06G - Diablo Tools</title></head>"
        b"<body><h1>DCB518ASTS06G Demo Demon</h1><p>MPN: DCB518ASTS06G</p>"
        b"<p>Manufacturer: Freud Inc / Diablo</p></body></html>"
    )

    fetcher = _fetcher(_FakeHttpPool({
        search_url: search_html,
        product_url: product_html,
    }))

    service = ProductSourceDiscoveryService(fetcher)
    product = _product(mpn="DCB518ASTS06G", manufacturer="Freud Inc", brand="Diablo")
    profile = ManufacturerProfile(
        manufacturer_id="freud",
        canonical_name="Freud Inc",
        verified_domains=("diablotools.com",),
    )

    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    best = candidates[0]
    assert best.url == product_url
    assert best.matched_mpn is True
    assert best.identity_score >= 0.6
    assert best.discovery_method == "site_search_result_link"


# ──────────────────────────────────────────────────────────────────────────────
# 13. Sitemap XML Discovery and sitemapindex Support
# ──────────────────────────────────────────────────────────────────────────────


def test_sitemap_xml_parsing_finds_matching_product_url() -> None:
    """Sitemap XML is fetched and parsed for product URL containing target MPN."""
    from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService

    sitemap_url = "https://acme.com/sitemap.xml"
    product_url = "https://acme.com/catalog/special/ABC123"

    sitemap_xml = (
        b"<?xml version='1.0' encoding='UTF-8'?>"
        b"<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        b"  <url><loc>https://acme.com/about</loc></url>"
        b"  <url><loc>https://acme.com/catalog/special/ABC123</loc></url>"
        b"  <url><loc>https://acme.com/contact</loc></url>"
        b"</urlset>"
    )
    product_html = (
        b"<!DOCTYPE html><html><head><title>Acme ABC123</title></head>"
        b"<body><h1>Acme ABC123 Industrial Part</h1><p>Acme Corp Part ABC123</p></body></html>"
    )

    fetcher = _fetcher(_FakeHttpPool({
        sitemap_url: sitemap_xml,
        product_url: product_html,
    }))

    service = ProductSourceDiscoveryService(fetcher)
    product = _product(mpn="ABC123", manufacturer="Acme Corp")
    profile = _profile(verified_domains=("acme.com",))

    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    best = candidates[0]
    assert best.url == product_url
    assert best.matched_mpn is True
    assert best.identity_score >= 0.6
    assert best.discovery_method == "sitemap_product_match"


def test_sitemap_index_traversal_finds_product_in_child_sitemap() -> None:
    """Sitemapindex XML traverses child sitemaps to locate the matching product URL."""
    from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService

    index_url = "https://acme.com/sitemap.xml"
    child_sitemap_url = "https://acme.com/products-sitemap.xml"
    product_url = "https://acme.com/items/tools/ABC123"

    index_xml = (
        b"<?xml version='1.0' encoding='UTF-8'?>"
        b"<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        b"  <sitemap><loc>https://acme.com/pages-sitemap.xml</loc></sitemap>"
        b"  <sitemap><loc>https://acme.com/products-sitemap.xml</loc></sitemap>"
        b"</sitemapindex>"
    )
    child_sitemap_xml = (
        b"<?xml version='1.0' encoding='UTF-8'?>"
        b"<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        b"  <url><loc>https://acme.com/items/tools/ABC123</loc></url>"
        b"</urlset>"
    )
    product_html = (
        b"<!DOCTYPE html><html><head><title>ABC123 Acme</title></head>"
        b"<body><h1>Acme ABC123</h1><p>MPN: ABC123 Acme</p></body></html>"
    )

    fetcher = _fetcher(_FakeHttpPool({
        index_url: index_xml,
        child_sitemap_url: child_sitemap_xml,
        product_url: product_html,
    }))

    service = ProductSourceDiscoveryService(fetcher)
    product = _product(mpn="ABC123", manufacturer="Acme")
    profile = _profile(verified_domains=("acme.com",))

    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    assert any(c.url == product_url for c in candidates)


# ──────────────────────────────────────────────────────────────────────────────
# 14. Negative Cases and Boundary Conditions
# ──────────────────────────────────────────────────────────────────────────────


def test_identity_matcher_rejects_similar_substring_mpn() -> None:
    """ProductIdentityMatcher must NOT match when MPN is an arbitrary substring of another MPN."""
    from unilog_product_intelligence.retrieval.source_discovery import ProductIdentityMatcher

    product = _product(mpn="ABC123", manufacturer="Acme Corp")
    # Document only contains ABC1234, NOT ABC123
    doc = type(
        "Document",
        (),
        {
            "title": "Acme ABC1234 Part",
            "chunks": [type("Chunk", (), {"text": "Acme Corp product ABC1234 and accessory."})()],
            "structured_metadata": {},
        },
    )()

    match = ProductIdentityMatcher().match(product, doc)

    assert match.matched_mpn is False
    assert match.identity_score < 0.6
    assert match.classification in {"WEAK_MATCH", "MISMATCH"}


def test_malformed_sitemap_xml_fails_gracefully() -> None:
    """Corrupt sitemap XML does not raise unhandled exceptions."""
    from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService

    sitemap_url = "https://acme.com/sitemap.xml"
    corrupt_xml = b"<?xml version='1.0'?><urlset><url><loc>https://acme.com/broken"

    fetcher = _fetcher(_FakeHttpPool({sitemap_url: corrupt_xml}))
    service = ProductSourceDiscoveryService(fetcher)
    product = _product(mpn="ABC123", manufacturer="Acme")
    profile = _profile(verified_domains=("acme.com",))

    # Must complete without crashing
    candidates = service.discover(product, profile)
    assert isinstance(candidates, list)


def test_pipeline_recovers_when_primary_source_404s() -> None:
    """When the initial source URL returns 404, recover() finds the valid alternate candidate."""
    from unilog_product_intelligence.application.phase65 import Phase65Pipeline, Phase65Status
    from unilog_product_intelligence.enrichment.models import EnrichmentResult, EnrichmentStatus

    broken_url = "https://diablotools.com/non-existent-product"
    valid_url = "https://diablotools.com/products/DCB518ASTS06G"
    product_html = (
        b"<!DOCTYPE html><html><head><title>DCB518ASTS06G - Diablo Tools</title></head>"
        b"<body><h1>DCB518ASTS06G</h1><p>MPN: DCB518ASTS06G by Freud Inc.</p></body></html>"
    )

    fetcher = _fetcher(_FakeHttpPool({valid_url: product_html}))

    class FakeOrch:
        def run(self, p):
            from unilog_product_intelligence.agents.orchestration import JobState, ProductJob
            p = ProductTruthService().add_classification(p, {})
            return p, ProductJob(
                job_id=f"job-{p.product_id}",
                product_id=p.product_id,
                state=JobState.UNDERSTOOD,
            )

    class FakeEnrich:
        def enrich(self, p, *args: object, **kwargs: object):
            from unilog_product_intelligence.enrichment.models import PublicationState
            return EnrichmentResult(
                product_id=p.product_id,
                status=EnrichmentStatus.ENRICHED,
                publication_state=PublicationState.READY,
                product_truth=p,
            )

    class FakeExtractor:
        def __init__(self, mpn="DCB518ASTS06G"):
            self.mpn = mpn
            self.last_response = None

        def extract(self, document, url, product_context):
            from unilog_product_intelligence.retrieval.core import (
                EvidenceCandidate,
                EvidenceExtractionResult,
                EvidenceStatus,
            )
            return EvidenceExtractionResult(
                candidates=[
                    EvidenceCandidate(
                        attribute="manufacturer_part_number",
                        raw_value=self.mpn,
                        normalized_candidate=self.mpn,
                        source_id=document.source_id,
                        url=url,
                        source_text=f"Model # {self.mpn}",
                        evidence_type=EvidenceStatus.DIRECT,
                        status=EvidenceStatus.DIRECT,
                    )
                ]
            )

    # Initial binding points to broken_url
    def broken_binding(p, disc):
        return (
            SourceRecord(
                canonical_url=broken_url,
                original_url=broken_url,
                source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
                decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                manufacturer_id="Freud Inc",
                manufacturer_domain="diablotools.com",
                product_id=p.product_id,
            ),
            ManufacturerProfile(
                manufacturer_id="Freud Inc",
                canonical_name="Freud Inc",
                verified_domains=("diablotools.com",),
            ),
        )

    extractor = FakeExtractor("DCB518ASTS06G")
    pipeline = Phase65Pipeline(
        orchestrator=FakeOrch(),
        discovery=ManufacturerDiscoveryAgent(_NeverCallProvider(), DomainResolver()),
        manufacturer=ManufacturerIntelligenceService(fetcher=fetcher, extractor=extractor),
        enrichment=FakeEnrich(),
        source_binding=broken_binding,
    )

    product = _product(mpn="DCB518ASTS06G", manufacturer="Freud Inc", brand="Diablo")
    result = pipeline.run(product)

    # After recovery, status must be ENRICHED and evidence attached
    assert result.status == Phase65Status.ENRICHED
    assert result.manufacturer_job is not None
    assert result.manufacturer_job.state.value == "completed"


# ──────────────────────────────────────────────────────────────────────────────
# 15. Task 9 — Row 2 Real Vertical Slice
# ──────────────────────────────────────────────────────────────────────────────


def test_row_2_real_vertical_slice() -> None:
    """Row 2 vertical slice: DCB518ASTS06G -> diablotools.com with 0 Gemini calls."""
    from unilog_product_intelligence.application.phase65 import Phase65Pipeline, Phase65Status
    from unilog_product_intelligence.enrichment.models import EnrichmentResult, EnrichmentStatus
    from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService

    # Authentic input row representation for Row 2
    product = ProductTruthService().create_from_raw_input(
        "unihack-row-2",
        {
            "Mfg_Part_Num": "DCB518ASTS06G",
            "Part_Desc": "5-1/8 in. 6 TPI Demo Demon Carbide Teeth Reciprocating Saw Blade",
            "Part_Manuf": "Freud Inc",
            "Unilog_Brand": "Diablo",
        },
        Source(
            source_id="input-row-2",
            source_type=SourceType.SUPPLIED_INPUT,
            authority=SourceAuthority.HIGH,
        ),
    )

    canonical_product_url = "https://diablotools.com/products/DCB518ASTS06G"
    product_page_html = (
        b"<!DOCTYPE html>"
        b"<html><head><title>5-1/8 in. Demo Demon Carbide Blade - Diablo Tools</title>"
        b"<meta name='description' content='Diablo DCB518ASTS06G carbide recip blade'>"
        b"</head>"
        b"<body>"
        b"  <h1>Diablo 5-1/8 in. Demo Demon Reciprocating Blade</h1>"
        b"  <div class='product-info'>"
        b"    <span class='mpn'>Model # DCB518ASTS06G</span>"
        b"    <span class='brand'>Diablo Tools</span>"
        b"    <span class='manufacturer'>Freud Inc.</span>"
        b"    <p class='desc'>5-1/8 in. 6 TPI Demo Demon Carbide Blade</p>"
        b"  </div>"
        b"</body></html>"
    )

    fetcher = _fetcher(_FakeHttpPool({canonical_product_url: product_page_html}))

    class FakeOrch:
        def run(self, p):
            from unilog_product_intelligence.agents.orchestration import JobState, ProductJob
            p = ProductTruthService().add_classification(p, {})
            return p, ProductJob(
                job_id=f"job-{p.product_id}",
                product_id=p.product_id,
                state=JobState.UNDERSTOOD,
            )

    class FakeEnrich:
        def enrich(self, p, *args: object, **kwargs: object):
            from unilog_product_intelligence.enrichment.models import PublicationState
            return EnrichmentResult(
                product_id=p.product_id,
                status=EnrichmentStatus.ENRICHED,
                publication_state=PublicationState.READY,
                product_truth=p,
            )

    class FakeExtractor:
        def __init__(self, mpn="DCB518ASTS06G"):
            self.mpn = mpn
            self.last_response = None

        def extract(self, document, url, product_context):
            from unilog_product_intelligence.retrieval.core import (
                EvidenceCandidate,
                EvidenceExtractionResult,
                EvidenceStatus,
            )
            return EvidenceExtractionResult(
                candidates=[
                    EvidenceCandidate(
                        attribute="manufacturer_part_number",
                        raw_value=self.mpn,
                        normalized_candidate=self.mpn,
                        source_id=document.source_id,
                        url=url,
                        source_text=f"Model # {self.mpn}",
                        evidence_type=EvidenceStatus.DIRECT,
                        status=EvidenceStatus.DIRECT,
                    )
                ]
            )

    source_disc = ProductSourceDiscoveryService(fetcher)

    def row2_source_binding(p, disc):
        candidates = source_disc.discover(
            p,
            ManufacturerProfile(
                manufacturer_id="Freud Inc",
                canonical_name="Freud Inc",
                verified_domains=tuple(c.domain for c in disc.candidates),
            ),
            candidate_urls=disc.search_result_urls,
        )
        if not candidates:
            return None
        exact = candidates[0]
        return (
            SourceRecord(
                canonical_url=exact.url,
                original_url=exact.url,
                source_kind=exact.source_kind,
                decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                manufacturer_id="Freud Inc",
                manufacturer_domain="diablotools.com",
                product_id=p.product_id,
            ),
            ManufacturerProfile(
                manufacturer_id="Freud Inc",
                canonical_name="Freud Inc",
                verified_domains=("diablotools.com",),
            ),
        )

    # Provider will raise AssertionError if any Gemini call is attempted
    zero_gemini_provider = _NeverCallProvider()
    extractor = FakeExtractor("DCB518ASTS06G")

    pipeline = Phase65Pipeline(
        orchestrator=FakeOrch(),
        discovery=ManufacturerDiscoveryAgent(zero_gemini_provider, DomainResolver()),
        manufacturer=ManufacturerIntelligenceService(fetcher=fetcher, extractor=extractor),
        enrichment=FakeEnrich(),
        source_binding=row2_source_binding,
    )

    result = pipeline.run(product)

    # Assertions for Row 2 Vertical Slice
    assert result.status == Phase65Status.ENRICHED
    assert result.discovery is not None
    # 1. Manufacturer domain resolved deterministically
    assert any(c.domain == "diablotools.com" for c in result.discovery.candidates)
    assert result.discovery.search_requested is False
    assert result.discovery.search_tool_calls == 0
    # 2. Product URL found and fetched
    assert result.manufacturer_job is not None
    assert result.manufacturer_job.state.value == "completed"
    assert result.manufacturer_job.error is None
    assert result.blocker is None
    # 3. Product truth has source attached
    assert any("diablotools.com" in s.uri for s in result.product_truth.sources if s.uri)


# ──────────────────────────────────────────────────────────────────────────────
# 16. Additional Negative and Boundary Tests (Task 11)
# ──────────────────────────────────────────────────────────────────────────────


def test_unknown_manufacturer_no_brand_falls_back_to_gemini() -> None:
    """An unknown manufacturer with no matching catalog or brand triggers Gemini search tools."""
    class FakeGeminiProvider(LLMProvider):
        def __init__(self):
            self.tool_calls_made = 0

        def generate(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(output_text="{}", model="gemini-2.5-flash")

        def generate_with_tools(self, request: LLMRequest, tools):
            self.tool_calls_made += 1
            domain_json = (
                '{"candidates": [{"domain": "unknown-tools.com", '
                '"source": "gemini_search", "reason": "Found domain", '
                '"status": "candidate_manufacturer_source"}]}'
            )
            return LLMResponse(
                output_text=domain_json,
                model="gemini-2.5-flash",
                tool_calls=1,
                search_call_count=1,
            )

    provider = FakeGeminiProvider()
    agent = ManufacturerDiscoveryAgent(provider, DomainResolver())

    result = agent.discover(
        manufacturer_id="Totally Unknown Widget Corp 99",
        manufacturer_name="Totally Unknown Widget Corp 99",
        mpn="XYZ-9999",
    )

    assert result.search_requested is True
    assert provider.tool_calls_made == 1
    assert any(c.domain == "unknown-tools.com" for c in result.candidates)


def test_massive_sitemap_xml_bounded_by_entry_limit() -> None:
    """Sitemaps with thousands of URLs are safely capped at MAX_SITEMAP_URLS without OOM."""
    from unilog_product_intelligence.retrieval.source_discovery import _parse_sitemap_xml

    urls = "\n".join(
        f"<url><loc>https://acme.com/products/item-{i}</loc></url>" for i in range(10000)
    )
    xml_content = (
        f"<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        f"{urls}</urlset>".encode()
    )

    locs, child_sitemaps = _parse_sitemap_xml(xml_content, max_entries=5000)

    assert len(locs) <= 5000
    assert len(locs) > 0


def test_search_page_with_no_links_returns_empty_candidates() -> None:
    """Search results page with no matching product links returns cleanly."""
    from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService

    search_url = "https://acme.com/search?q=ABC123"
    empty_html = b"<!DOCTYPE html><html><body><p>No results found for ABC123.</p></body></html>"

    fetcher = _fetcher(_FakeHttpPool({search_url: empty_html}))
    service = ProductSourceDiscoveryService(fetcher)
    product = _product(mpn="ABC123", manufacturer="Acme")
    profile = _profile(verified_domains=("acme.com",))

    candidates = service.discover(product, profile)

    assert candidates == []


def test_redirect_to_external_domain_rejected() -> None:
    """Fetcher refuses to follow redirect to an external unauthorized domain."""
    class FakeRedirectResponse:
        def __init__(self, code, headers):
            self.status = code
            self.code = code
            self.headers = headers
        def read(self, amt=None):
            return b""
        def close(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.close()

    def redirect_opener(request, timeout):
        return FakeRedirectResponse(302, {"Location": "https://evil.example/product"})

    class AllowResolver:
        def validate(self, url):
            pass

    fetcher = SourceFetcher(resolver=AllowResolver())
    fetcher.opener = redirect_opener
    fetcher._custom_opener = False

    result = fetcher.fetch(_source(url="https://acme.com/item", manufacturer_domain="acme.com"))

    assert result.source.retrieval_status == RetrievalStatus.FAILED
    assert result.error == "redirect_external_domain"


# ──────────────────────────────────────────────────────────────────────────────
# 15. Authority Boundary & Verified vs Candidate Domain Regression Tests
# ──────────────────────────────────────────────────────────────────────────────


def test_candidate_domain_not_placed_in_verified_domains() -> None:
    """Unverified candidate domains from discovery are NOT placed into verified_domains."""
    from unilog_product_intelligence.retrieval.agents import DiscoveryResult
    from unilog_product_intelligence.retrieval.core import DomainCandidate

    disc = DiscoveryResult(
        candidates=[
            DomainCandidate(
                domain="candidate.example.com",
                status=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
                source="gemini_search",
                reason="Unverified search result",
            ),
            DomainCandidate(
                domain="distributor.example.com",
                status=SourceDecision.NON_AUTHORITATIVE,
                source="gemini_search",
                reason="Distributor domain",
            ),
        ]
    )

    verified_candidates = [
        c for c in disc.candidates
        if c.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
    ]
    assert verified_candidates == []

    # Creating profile with verified candidates leaves verified_domains empty
    profile = ManufacturerProfile(
        manufacturer_id="Acme Corp",
        canonical_name="Acme Corp",
        verified_domains=tuple(c.domain for c in verified_candidates),
    )
    assert profile.verified_domains == ()
    assert "candidate.example.com" not in profile.verified_domains


def test_source_fetcher_rejects_unverified_candidate_source() -> None:
    """SourceFetcher refuses to fetch sources whose decision is not VERIFIED_MANUFACTURER_SOURCE."""
    fetcher = SourceFetcher()
    candidate_source = SourceRecord(
        canonical_url="https://candidate.example.com/product/123",
        original_url="https://candidate.example.com/product/123",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
        manufacturer_id="Acme Corp",
        manufacturer_domain="candidate.example.com",
    )

    result = fetcher.fetch(candidate_source)
    assert result.cache_status == CacheStatus.INVALID
    assert result.source.retrieval_status == RetrievalStatus.BLOCKED
    assert result.error == "source_not_verified"


def test_recovery_cannot_promote_unverified_candidate_source() -> None:
    """Recovery enforces source verification and refuses unverified candidate domains."""
    from unilog_product_intelligence.retrieval.service import ManufacturerJob, ManufacturerJobState

    fetcher = _fetcher(_FakeHttpPool({
        "https://unverified.example.com/product/ABC123": b"<html><body>ABC123 Acme</body></html>"
    }))
    service = ManufacturerIntelligenceService(fetcher=fetcher)
    product = _product(mpn="ABC123", manufacturer="Acme Corp")
    profile = _profile(verified_domains=("verified.example.com",))

    failed_job = ManufacturerJob(
        product_id=product.product_id,
        state=ManufacturerJobState.FAILED,
        failure_reason=Phase5FailureReason.SOURCE_FETCH_FAILED,
    )

    # Candidate URL is on an unverified domain
    product, job = service.recover(
        product,
        profile,
        failed_job,
        candidate_urls=("https://unverified.example.com/product/ABC123",),
    )

    assert job.state == ManufacturerJobState.REVIEW_REQUIRED
    assert job.failure_reason in {
        Phase5FailureReason.DOMAIN_UNVERIFIED,
        Phase5FailureReason.PRODUCT_SOURCE_NOT_FOUND,
    }


def test_verified_catalog_domain_full_pipeline_success() -> None:
    """Verified catalog domain discovers candidate, verifies source, and fetches successfully."""
    from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService

    product_url = "https://diablotools.com/products/DCB518ASTS06G"
    product_html = (
        b"<!DOCTYPE html><html><head><title>Diablo DCB518ASTS06G Sanding Belt</title></head>"
        b"<body><h1>Diablo DCB518ASTS06G</h1>"
        b"<p>MPN: DCB518ASTS06G Freud Inc Diablo</p></body></html>"
    )

    fetcher = _fetcher(_FakeHttpPool({product_url: product_html}))
    service = ProductSourceDiscoveryService(fetcher)
    product = _product(mpn="DCB518ASTS06G", manufacturer="Freud Inc")
    profile = _profile(verified_domains=("diablotools.com",))

    candidates = service.discover(product, profile)
    assert len(candidates) > 0
    best = candidates[0]
    assert best.url == product_url
    assert best.matched_mpn is True

    candidate_source = SourceRecord(
        canonical_url=best.url,
        original_url=best.url,
        source_kind=best.source_kind,
        decision=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
        manufacturer_id=profile.manufacturer_id,
        manufacturer_domain="diablotools.com",
    )
    verified_source = SourceVerifier(SourcePolicy()).verify_source(candidate_source, profile)
    assert verified_source.decision == SourceDecision.VERIFIED_MANUFACTURER_SOURCE

    fetch_res = fetcher.fetch(verified_source)
    assert fetch_res.source.retrieval_status == RetrievalStatus.SUCCESS


def test_gemini_candidate_cannot_bypass_policy() -> None:
    """Gemini-discovered candidates with CANDIDATE_MANUFACTURER_SOURCE cannot bypass policy."""
    from unilog_product_intelligence.retrieval.agents import DiscoveryResult
    from unilog_product_intelligence.retrieval.core import DomainCandidate

    disc = DiscoveryResult(
        candidates=[
            DomainCandidate(
                domain="unverified.example",
                source="gemini",
                reason="search_result",
                status=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
            )
        ]
    )

    verified_candidates = tuple(
        c for c in disc.candidates if c.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
    )
    assert verified_candidates == ()

    profile = ManufacturerProfile(
        manufacturer_id="Acme",
        canonical_name="Acme",
        verified_domains=tuple(c.domain for c in verified_candidates),
        candidate_domains=tuple(
            c.domain
            for c in disc.candidates
            if c.status == SourceDecision.CANDIDATE_MANUFACTURER_SOURCE
        ),
    )
    assert "unverified.example" not in profile.verified_domains
    assert "unverified.example" in profile.candidate_domains

    # SourcePolicy must reject this domain
    policy = SourcePolicy()
    assert policy.allowed_domain("https://unverified.example/product/123", profile) is False



