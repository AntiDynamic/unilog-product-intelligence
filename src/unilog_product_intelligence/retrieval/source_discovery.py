"""Deterministic exact-product source discovery after manufacturer-domain discovery."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.domain.truth import ProductTruth
from unilog_product_intelligence.retrieval.mpn_normalizer import (
    MpnHypothesis,
    MpnHypothesisType,
    MpnNormalizer,
)

from .core import (
    AsyncSourceFetcher,
    DocumentLink,
    DomainCircuitBreaker,
    FetchResult,
    HtmlParser,
    ManufacturerProfile,
    PdfParser,
    RetrievalStatus,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourceRecord,
    canonicalize_url,
)


@dataclass(frozen=True)
class ManufacturerRetrievalProfile:
    """Manufacturer-specific search endpoints and path patterns."""

    name: str
    domains: tuple[str, ...]
    search_url_templates: tuple[str, ...] = ()
    direct_path_templates: tuple[str, ...] = ()
    product_link_patterns: tuple[str, ...] = ()


_RETRIEVAL_PROFILES: tuple[ManufacturerRetrievalProfile, ...] = (
    ManufacturerRetrievalProfile(
        name="milwaukee",
        domains=("www.milwaukeetool.com", "milwaukeetool.com"),
        search_url_templates=(
            "https://www.milwaukeetool.com/search?q={mpn}",
            "https://www.milwaukeetool.com/Search/Products?q={mpn}",
            "https://www.milwaukeetool.com/search?query={mpn}",
        ),
        direct_path_templates=(
            "https://www.milwaukeetool.com/Products/{mpn}",
            "https://www.milwaukeetool.com/products/{mpn}",
            "https://www.milwaukeetool.com/Products/Accessories/{mpn}",
        ),
        product_link_patterns=("/products/", "/product/"),
    ),
    ManufacturerRetrievalProfile(
        name="3m",
        domains=("www.3m.com", "3m.com", "multimedia.3m.com"),
        search_url_templates=(
            "https://www.3m.com/3M/en_US/search/?q={mpn}",
            "https://www.3m.com/3M/en_US/search/?Ntt={mpn}",
            "https://www.3m.com/3M/en_US/search/results?search={mpn}",
            "https://www.3m.com/3M/en_US/company-us/search/?Ntt={mpn}",
            "https://www.3m.com/search?q={mpn}",
        ),
        direct_path_templates=(
            "https://www.3m.com/3M/en_US/p/d/{mpn}/",
            "https://www.3m.com/3M/en_US/p/d/b{mpn}/",
            "https://www.3m.com/3M/en_US/p/d/v{mpn}/",
            "https://www.3m.com/3M/en_US/company-us/all-3m-products/~/p/?Ntt={mpn}",
            "https://www.3m.com/products/{mpn}",
        ),
        product_link_patterns=(
            "/p/d/",
            "/products/",
            "/product/",
            "/all-3m-products/",
            "/p/c/",
            "/p/",
            ".pdf",
            "/mws/media/",
        ),
    ),
    ManufacturerRetrievalProfile(
        name="diablo",
        domains=("diablotools.com", "freudtools.com", "www.diablotools.com", "www.freudtools.com"),
        search_url_templates=(
            "https://diablotools.com/search?q={mpn}",
            "https://diablotools.com/search?keywords={mpn}",
        ),
        direct_path_templates=(
            "https://diablotools.com/products/{mpn}",
            "https://diablotools.com/product/{mpn}",
        ),
        product_link_patterns=("/products/", "/product/"),
    ),
    ManufacturerRetrievalProfile(
        name="mirka",
        domains=("mirka.com", "mirkausa.com", "www.mirka.com"),
        search_url_templates=(
            "https://www.mirka.com/en-US/search/?q={mpn}",
            "https://www.mirka.com/search?q={mpn}",
        ),
        direct_path_templates=(
            "https://www.mirka.com/en-US/products/{mpn}",
            "https://www.mirka.com/products/{mpn}",
        ),
        product_link_patterns=("/products/", "/product/"),
    ),
    ManufacturerRetrievalProfile(
        name="frigidaire",
        domains=(
            "frigidaire.com",
            "www.frigidaire.com",
            "electroluxappliances.com",
            "electrolux.com",
        ),
        search_url_templates=(
            "https://www.frigidaire.com/search?q={mpn}",
            "https://www.frigidaire.com/Owner-Center/Product-Support/{mpn}/",
        ),
        direct_path_templates=(
            "https://www.frigidaire.com/en/p/owner-center/product-support/{mpn}",
            "https://www.frigidaire.com/Owner-Center/Product-Support/{mpn}/",
            "https://www.frigidaire.com/products/{mpn}",
            "https://www.frigidaire.com/product/{mpn}",
            "https://www.frigidaire.com/p/{mpn}",
        ),
        product_link_patterns=(
            "/owner-center/product-support/",
            "/product-support/",
            "/products/",
            "/product/",
            "/p/",
            ".pdf",
        ),
    ),
    ManufacturerRetrievalProfile(
        name="whirlpool",
        domains=(
            "whirlpool.com",
            "www.whirlpool.com",
            "learnwhirlpool.com",
            "producthelp.whirlpool.com",
        ),
        search_url_templates=(
            "https://learnwhirlpool.com/smartsearchresults?searchtext={mpn}",
            "https://learnwhirlpool.com/?searchtext={mpn}",
            "https://www.whirlpool.com/search?query={mpn}",
        ),
        direct_path_templates=(
            "https://learnwhirlpool.com/learningitem/{mpn}-product-brief",
            "https://www.whirlpool.com/products/{mpn}",
            "https://www.whirlpool.com/product/{mpn}",
            "https://www.whirlpool.com/pdp/{mpn}",
        ),
        product_link_patterns=(
            "/learningitem/",
            "/pdp.",
            "/products/",
            "/product/",
            ".pdf",
            "/documents/",
        ),
    ),
)


def _get_retrieval_profile(domains: tuple[str, ...]) -> ManufacturerRetrievalProfile | None:
    for profile in _RETRIEVAL_PROFILES:
        if any(any(_same_or_subdomain(d, prof_d) for prof_d in profile.domains) for d in domains):
            return profile
    return None


class MpnMatchClassification(StrEnum):
    RAW_EXACT = "RAW_EXACT"
    LOSSLESS_NORMALIZED = "LOSSLESS_NORMALIZED"
    VERIFIED_TRANSFORMED = "VERIFIED_TRANSFORMED"
    EXPLORATORY_ONLY = "EXPLORATORY_ONLY"
    NO_MATCH = "NO_MATCH"


class ProductSourceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    title: str | None = None
    source_kind: SourceKind
    discovery_method: str
    evidence_snippet: str
    matched_mpn: bool
    matched_manufacturer: bool
    matched_brand: bool
    identity_score: float = Field(ge=0, le=1)
    domain_score: float = Field(ge=0, le=1)
    relevance_score: float = Field(ge=0, le=1)
    mpn_match_type: MpnMatchClassification = MpnMatchClassification.NO_MATCH
    raw_mpn_match: bool = False
    normalized_mpn_match: bool = False
    transformed_mpn_match: bool = False
    rejection_reason: str | None = None


def _rank_verified_domains(
    product: ProductTruth,
    profile: ManufacturerProfile,
    retrieval_profile: ManufacturerRetrievalProfile | None = None,
) -> tuple[str, ...]:
    """Rank verified manufacturer domains deterministically without speculative assumptions."""
    if not profile.verified_domains:
        return ()

    domains = tuple(_host(d) for d in profile.verified_domains if d)
    if not domains:
        return ()

    unique_domains = tuple(dict.fromkeys(domains))
    profile_domains: set[str] = set()
    if retrieval_profile:
        profile_domains = {_host(d) for d in retrieval_profile.domains}

    preferred = [d for d in unique_domains if d in profile_domains]
    remainder = [d for d in unique_domains if d not in profile_domains]
    return tuple(preferred + remainder)


def _order_mpn_hypotheses_for_retrieval(
    hypotheses: list[MpnHypothesis],
) -> list[MpnHypothesis]:
    """Order MPN hypotheses by confidence and search safety for strategy execution."""
    priority_map = {
        MpnHypothesisType.RAW: 1,
        MpnHypothesisType.LOSSLESS_NORMALIZED: 2,
        MpnHypothesisType.VERIFIED_MANUFACTURER_TRANSFORM: 3,
        MpnHypothesisType.EXPLORATORY_PREFIX_STRIP: 4,
        MpnHypothesisType.EXPLORATORY_NUMERIC_EXTRACTION: 5,
        MpnHypothesisType.EXPLORATORY_COMPACT: 6,
        MpnHypothesisType.STRIPPED_DISTRIBUTOR_PREFIX: 4,
        MpnHypothesisType.NUMERIC_CORE_ID: 5,
        MpnHypothesisType.ALPHANUMERIC_COMPACT: 6,
    }
    return sorted(
        hypotheses,
        key=lambda h: (
            priority_map.get(h.hypothesis_type, 99),
            -h.confidence,
            not h.identity_eligible,
        ),
    )


class ManufacturerRetrievalStrategy(Protocol):
    name: str

    def matches(self, profile: ManufacturerProfile, domains: tuple[str, ...]) -> bool: ...

    def direct_path_urls(
        self,
        domain: str,
        hypotheses: list[MpnHypothesis],
        product: ProductTruth,
        profile: ManufacturerProfile,
    ) -> list[str]: ...

    def search_urls(
        self,
        domain: str,
        hypotheses: list[MpnHypothesis],
        product: ProductTruth,
        profile: ManufacturerProfile,
    ) -> list[str]: ...

    def is_product_link(
        self,
        link: DocumentLink,
        mpn_hypotheses: list[MpnHypothesis],
        domains: tuple[str, ...],
    ) -> bool: ...


class ThreeMRetrievalStrategy:
    """Specialized retrieval strategy for 3M products, catalog pages, and document fallbacks."""

    name: str = "3m"
    domains: tuple[str, ...] = ("www.3m.com", "3m.com", "multimedia.3m.com")

    direct_path_templates: tuple[str, ...] = (
        "https://www.3m.com/3M/en_US/p/d/{mpn}/",
        "https://www.3m.com/3M/en_US/p/d/b{mpn}/",
        "https://www.3m.com/3M/en_US/p/d/v{mpn}/",
        "https://www.3m.com/3M/en_US/company-us/all-3m-products/~/p/?Ntt={mpn}",
        "https://www.3m.com/products/{mpn}",
    )

    search_url_templates: tuple[str, ...] = (
        "https://www.3m.com/3M/en_US/search/?q={mpn}",
        "https://www.3m.com/3M/en_US/search/?Ntt={mpn}",
        "https://www.3m.com/3M/en_US/search/results?search={mpn}",
        "https://www.3m.com/3M/en_US/company-us/search/?Ntt={mpn}",
        "https://www.3m.com/search?q={mpn}",
    )

    product_link_patterns: tuple[str, ...] = (
        "/p/d/",
        "/products/",
        "/product/",
        "/all-3m-products/",
        "/p/c/",
        "/p/",
        ".pdf",
        "/mws/media/",
    )

    def matches(self, profile: ManufacturerProfile, domains: tuple[str, ...]) -> bool:
        mfg_id = profile.manufacturer_id.casefold()
        canonical = (profile.canonical_name or "").casefold()
        if "3m" in mfg_id or "3m" in canonical:
            return True
        return any(any(_same_or_subdomain(d, pd) for pd in self.domains) for d in domains)

    def direct_path_urls(
        self,
        domain: str,
        hypotheses: list[MpnHypothesis],
        product: ProductTruth,
        profile: ManufacturerProfile,
    ) -> list[str]:
        urls: list[str] = []
        for tmpl in self.direct_path_templates:
            for hyp in hypotheses:
                try:
                    urls.append(tmpl.format(mpn=hyp.value, domain=domain))
                except KeyError:
                    urls.append(tmpl.format(mpn=hyp.value))
        return urls

    def search_urls(
        self,
        domain: str,
        hypotheses: list[MpnHypothesis],
        product: ProductTruth,
        profile: ManufacturerProfile,
    ) -> list[str]:
        urls: list[str] = []
        for tmpl in self.search_url_templates:
            for hyp in hypotheses:
                try:
                    urls.append(tmpl.format(mpn=hyp.value, domain=domain))
                except KeyError:
                    urls.append(tmpl.format(mpn=hyp.value))
        return urls

    def is_product_link(
        self,
        link: DocumentLink,
        mpn_hypotheses: list[MpnHypothesis],
        domains: tuple[str, ...],
    ) -> bool:
        allowed = domains + self.domains
        if not any(_same_or_subdomain(_host(link.url), d) for d in allowed):
            return False
        text = f"{link.anchor_text} {link.url}".casefold()
        if any(_identity_present(hyp.value, text) for hyp in mpn_hypotheses):
            return True
        path = urlsplit(link.url).path.casefold()
        return any(pat in path for pat in self.product_link_patterns)


class MirkaRetrievalStrategy:
    """Specialized retrieval strategy for Mirka abrasives, polishers, and tools."""

    name: str = "mirka"
    domains: tuple[str, ...] = ("www.mirka.com", "mirka.com", "mirkausa.com")

    direct_path_templates: tuple[str, ...] = (
        "https://www.mirka.com/en-us/products/{mpn}",
        "https://www.mirka.com/en-US/products/{mpn}",
        "https://www.mirka.com/en/products/{mpn}",
        "https://www.mirka.com/products/{mpn}",
        "https://www.mirka.com/en-us/products/abrasives-and-compounds/abrasives/{mpn}",
    )

    search_url_templates: tuple[str, ...] = (
        "https://www.mirka.com/en-us/search/?searchTerm={mpn}",
        "https://www.mirka.com/en-us/search/?searchTerm={mpn}&tab=products",
        "https://www.mirka.com/en-us/search?q={mpn}",
    )

    product_link_patterns: tuple[str, ...] = (
        "/en-us/products/",
        "/products/",
        "/product/",
        "/detail",
        ".pdf",
    )

    def matches(self, profile: ManufacturerProfile, domains: tuple[str, ...]) -> bool:
        mfg_id = profile.manufacturer_id.casefold()
        canonical = (profile.canonical_name or "").casefold()
        if "mirka" in mfg_id or "mirka" in canonical:
            return True
        return any(any(_same_or_subdomain(d, pd) for pd in self.domains) for d in domains)

    def direct_path_urls(
        self,
        domain: str,
        hypotheses: list[MpnHypothesis],
        product: ProductTruth,
        profile: ManufacturerProfile,
    ) -> list[str]:
        urls: list[str] = []
        for tmpl in self.direct_path_templates:
            for hyp in hypotheses:
                try:
                    urls.append(tmpl.format(mpn=hyp.value, domain=domain))
                except KeyError:
                    urls.append(tmpl.format(mpn=hyp.value))
        return urls

    def search_urls(
        self,
        domain: str,
        hypotheses: list[MpnHypothesis],
        product: ProductTruth,
        profile: ManufacturerProfile,
    ) -> list[str]:
        urls: list[str] = []
        for tmpl in self.search_url_templates:
            for hyp in hypotheses:
                try:
                    urls.append(tmpl.format(mpn=hyp.value, domain=domain))
                except KeyError:
                    urls.append(tmpl.format(mpn=hyp.value))

        # Include product family keywords from Part_Desc
        desc = str(product.raw_value("Part_Desc") or "").casefold()
        mirka_kws = (
            "hiolit", "abranet", "abralon", "iridium", "galaxy", "mirlon", "gold", "polarstar"
        )
        for kw in mirka_kws:
            if kw in desc:
                urls.append(f"https://www.mirka.com/en-us/search/?searchTerm={kw.upper()}")
                urls.append(
                    f"https://www.mirka.com/en-us/search/?searchTerm={kw.upper()}&tab=products"
                )

        return urls

    def is_product_link(
        self,
        link: DocumentLink,
        mpn_hypotheses: list[MpnHypothesis],
        domains: tuple[str, ...],
    ) -> bool:
        allowed = domains + self.domains
        if not any(_same_or_subdomain(_host(link.url), d) for d in allowed):
            return False
        text = f"{link.anchor_text} {link.url}".casefold()
        if any(_identity_present(hyp.value, text) for hyp in mpn_hypotheses):
            return True
        path = urlsplit(link.url).path.casefold()
        return any(pat in path for pat in self.product_link_patterns)


class AuthorizedDistributorFallbackStrategy:
    """Secondary fallback retrieval strategy targeting authorized distributors."""

    name: str = "authorized_distributor_fallback"
    domains: tuple[str, ...] = (
        "www.jamindustrialsupply.com",
        "jamindustrialsupply.com",
        "www.zoro.com",
        "zoro.com",
        "www.grainger.com",
        "grainger.com",
    )

    def generate_urls(self, product: ProductTruth, hypotheses: list[MpnHypothesis]) -> list[str]:
        mfg = _product_value(product, "manufacturer") or str(
            product.raw_value("Part_Manuf") or ""
        ).strip()
        clean_mfg = re.sub(r"\s*\([^)]*\)", "", mfg).strip()

        urls: list[str] = []
        for hyp in hypotheses:
            val = hyp.value.strip()
            if not val:
                continue
            # Direct distributor URLs
            urls.append(f"https://www.jamindustrialsupply.com/?s={val}&post_type=product")
            urls.append(f"https://www.jamindustrialsupply.com/part-number/{val}/")
            urls.append(f"https://www.jamindustrialsupply.com/product-id/{val}/")
            urls.append(f"https://www.jamindustrialsupply.com/3m-{val}")
            urls.append(f"https://www.jamindustrialsupply.com/mirka-{val}")
            urls.append(f"https://www.jamindustrialsupply.com/{val}")
            urls.append(f"https://www.zoro.com/search?q={clean_mfg}+{val}")
            urls.append(f"https://www.grainger.com/search?searchQuery={val}")
        return urls


class GenericManufacturerRetrievalStrategy:
    """Default retrieval strategy using standard URL conventions and profiles."""

    name: str = "generic"

    def __init__(
        self,
        url_strategy: DeterministicUrlStrategy,
        profile_match: ManufacturerRetrievalProfile | None = None,
    ) -> None:
        self.url_strategy = url_strategy
        self.profile = profile_match

    def matches(self, profile: ManufacturerProfile, domains: tuple[str, ...]) -> bool:
        return True

    def direct_path_urls(
        self,
        domain: str,
        hypotheses: list[MpnHypothesis],
        product: ProductTruth,
        profile: ManufacturerProfile,
    ) -> list[str]:
        urls: list[str] = []
        # Try manufacturer-specific routes first. The caller bounds the list,
        # so appending these after generic guesses can otherwise prevent exact
        # support/product URLs from ever being fetched.
        if self.profile:
            for tmpl in self.profile.direct_path_templates:
                for hyp in hypotheses:
                    try:
                        urls.append(tmpl.format(mpn=hyp.value, domain=domain))
                    except KeyError:
                        urls.append(tmpl.format(mpn=hyp.value))
        for hyp in hypotheses:
            urls.extend(self.url_strategy.direct_product_paths(domain, hyp.value))
        return urls

    def search_urls(
        self,
        domain: str,
        hypotheses: list[MpnHypothesis],
        product: ProductTruth,
        profile: ManufacturerProfile,
    ) -> list[str]:
        urls: list[str] = []
        if self.profile and self.profile.search_url_templates:
            for tmpl in self.profile.search_url_templates:
                for hyp in hypotheses:
                    try:
                        urls.append(tmpl.format(mpn=hyp.value, domain=domain))
                    except KeyError:
                        urls.append(tmpl.format(mpn=hyp.value))
        else:
            for hyp in hypotheses:
                urls.extend(self.url_strategy.site_search_candidates(domain, hyp.value))
        return urls

    def is_product_link(
        self,
        link: DocumentLink,
        mpn_hypotheses: list[MpnHypothesis],
        domains: tuple[str, ...],
    ) -> bool:
        return _is_search_result_product_link(link, mpn_hypotheses, domains, self.profile)


_SPECIALIZED_STRATEGIES: tuple[ManufacturerRetrievalStrategy, ...] = (
    ThreeMRetrievalStrategy(),
    MirkaRetrievalStrategy(),
)


def _get_manufacturer_strategy(
    profile: ManufacturerProfile,
    domains: tuple[str, ...],
    url_strategy: DeterministicUrlStrategy,
) -> ManufacturerRetrievalStrategy:
    for strat in _SPECIALIZED_STRATEGIES:
        if strat.matches(profile, domains):
            return strat
    retrieval_profile = _get_retrieval_profile(domains)
    return GenericManufacturerRetrievalStrategy(url_strategy, retrieval_profile)


class ProductSourceDiscoveryService:
    """Find exact product sources with ranked, bounded, asynchronous strategy execution.

    Executes unified deterministic retrieval strategies across all verified manufacturer domains:
      1. Candidate URLs supplied by caller or prior steps
      2. Domain-by-domain concurrent search across ranked verified domains:
         a. Direct product URL path patterns (testing ordered MPN hypotheses)
         b. Targeted site-search probe & link extraction (multiple search templates)
         c. Sitemap discovery (testing multiple sitemap candidates & child sitemaps)
      3. Authorized distributor secondary fallback

    Short-circuits immediately upon discovering an exact high-confidence product match.
    """

    def __init__(
        self,
        fetcher: SourceFetcher | AsyncSourceFetcher | None = None,
        minimum_score: float = 0.6,
        max_candidates: int = 64,
        url_strategy: DeterministicUrlStrategy | None = None,
        max_domains: int = 3,
        max_hypotheses: int = 4,
        max_direct_candidates_per_domain: int = 4,
        max_search_templates_per_domain: int = 3,
        max_search_result_links: int = 3,
        max_sitemap_paths_per_domain: int = 3,
        max_child_sitemaps: int = 3,
        circuit_breaker: DomainCircuitBreaker | None = None,
    ) -> None:
        self.fetcher = fetcher or SourceFetcher()
        self.minimum_score = minimum_score
        self.max_candidates = max_candidates
        self.url_strategy = url_strategy or DeterministicUrlStrategy()
        self.max_domains = max_domains
        self.max_hypotheses = max_hypotheses
        self.max_direct_candidates_per_domain = max_direct_candidates_per_domain
        self.max_search_templates_per_domain = max_search_templates_per_domain
        self.max_search_result_links = max_search_result_links
        self.max_sitemap_paths_per_domain = max_sitemap_paths_per_domain
        self.max_child_sitemaps = max_child_sitemaps
        self.circuit_breaker = (
            circuit_breaker
            or getattr(self.fetcher, "circuit_breaker", None)
            or DomainCircuitBreaker()
        )

        self.verified_domains_available: tuple[str, ...] = ()
        self.domains_attempted: tuple[str, ...] = ()
        self.selected_domain: str | None = None
        self.domain_attempt_failure_reasons: dict[str, str] = {}

    async def adiscover(
        self,
        product: ProductTruth,
        profile: ManufacturerProfile,
        candidate_urls: Iterable[str] = (),
    ) -> list[ProductSourceCandidate]:
        raw_mpn = _product_value(product, "manufacturer_part_number") or str(
            product.raw_value("Mfg_Part_Num") or ""
        ).strip()
        normalizer = MpnNormalizer()
        mfg_hint = (
            f"{profile.canonical_name or profile.manufacturer_id} "
            f"{product.raw_value('Unilog_Brand') or ''}"
        ).strip()
        raw_hypotheses = normalizer.normalize(raw_mpn, manufacturer_hint=mfg_hint)
        mpn_hypotheses = _order_mpn_hypotheses_for_retrieval(raw_hypotheses)

        domains = tuple(_host(domain) for domain in profile.verified_domains if domain)
        if not domains:
            domains = tuple(_host(domain) for domain in profile.candidate_domains if domain)
        if not domains:
            return []

        retrieval_profile = _get_retrieval_profile(domains)
        ranked_domains = _rank_verified_domains(product, profile, retrieval_profile)[
            : self.max_domains
        ]

        self.verified_domains_available = tuple(domains)
        attempted_domains: list[str] = []
        domain_failures: dict[str, str] = {}
        self.selected_domain = None

        mfg_strategy = _get_manufacturer_strategy(profile, ranked_domains, self.url_strategy)

        seen: set[str] = set()
        candidates: list[ProductSourceCandidate] = []
        matcher = ProductIdentityMatcher()

        async def _test_url(
            url: str,
            method: str,
            allowed_domains: tuple[str, ...] | None = None,
            is_secondary_distributor: bool = False,
        ) -> ProductSourceCandidate | None:
            try:
                norm_url = canonicalize_url(url)
            except ValueError:
                return None
            target_host = _host(norm_url)
            if not self.circuit_breaker.is_available(target_host):
                return None
            effective_domains = allowed_domains or domains
            if norm_url in seen or not any(
                _same_or_subdomain(target_host, d) for d in effective_domains
            ):
                return None
            seen.add(norm_url)

            source_kind = (
                SourceKind.DISTRIBUTOR_PRODUCT_PAGE
                if is_secondary_distributor
                else _source_kind(norm_url)
            )
            decision = (
                SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE
                if is_secondary_distributor
                else SourceDecision.VERIFIED_MANUFACTURER_SOURCE
            )
            source = SourceRecord(
                canonical_url=norm_url,
                original_url=norm_url,
                source_kind=source_kind,
                decision=decision,
                manufacturer_id=profile.manufacturer_id,
                manufacturer_domain=target_host,
                verified_domains=profile.verified_domains if not is_secondary_distributor else (),
                product_id=product.product_id,
            )

            if hasattr(self.fetcher, "fetch_async"):
                fetched = await self.fetcher.fetch_async(source)
            else:
                fetched = await asyncio.to_thread(self.fetcher.fetch, source)

            if fetched.source.retrieval_status is not RetrievalStatus.SUCCESS:
                if (
                    fetched.source.retrieval_status == RetrievalStatus.BLOCKED
                    or fetched.source.http_status in {403, 429}
                ):
                    self.circuit_breaker.record_failure(target_host, "waf_blocked")
                    domain_failures[target_host] = "waf_blocked"
                return None

            content_type = fetched.source.content_type or ""
            valid_types = {"text/html", "text/plain", "application/pdf", "application/json"}
            if content_type not in valid_types:
                return None

            try:
                parser = PdfParser() if content_type == "application/pdf" else HtmlParser()
                document = parser.parse(fetched)
            except Exception:
                return None

            match = matcher.match(product, document)
            if match.identity_score >= self.minimum_score:
                canonical = document.canonical_url or fetched.source.canonical_url or norm_url
                if not any(_same_or_subdomain(_host(canonical), d) for d in effective_domains):
                    canonical = fetched.source.canonical_url or norm_url
                cand = ProductSourceCandidate(
                    url=canonical,
                    title=document.title,
                    source_kind=source_kind,
                    discovery_method=method,
                    evidence_snippet=_snippet(document, raw_mpn),
                    matched_mpn=match.matched_mpn,
                    matched_manufacturer=match.matched_manufacturer,
                    matched_brand=match.matched_brand,
                    identity_score=match.identity_score,
                    domain_score=0.75 if is_secondary_distributor else 1.0,
                    relevance_score=match.relevance_score,
                    mpn_match_type=match.mpn_match_type,
                    raw_mpn_match=match.raw_mpn_match,
                    normalized_mpn_match=match.normalized_mpn_match,
                    transformed_mpn_match=match.transformed_mpn_match,
                    rejection_reason=match.rejection_reason,
                )
                return cand
            return None

        # ── PHASE 1: Caller-supplied Candidate URLs ───────────────────────────
        supplied_urls = list(candidate_urls)[: self.max_direct_candidates_per_domain]
        if supplied_urls:
            tasks = [_test_url(u, "supplied_candidate_url") for u in supplied_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, ProductSourceCandidate):
                    candidates.append(r)
                    if (
                        r.identity_score >= self.minimum_score
                        and r.matched_mpn
                        and r.domain_score >= 1.0
                    ):
                        self.selected_domain = _host(r.url)
                        self.domains_attempted = tuple(attempted_domains) or (_host(r.url),)
                        self.domain_attempt_failure_reasons = domain_failures
                        return sorted(candidates, key=_candidate_rank)

        # ── PHASE 2: Domain-by-Domain Iteration ──────────────────────────────
        for domain in ranked_domains:
            if not self.circuit_breaker.is_available(domain):
                continue
            attempted_domains.append(domain)

            # --- A. Direct Product Paths (Concurrent within domain) ---
            direct_urls = mfg_strategy.direct_path_urls(
                domain, mpn_hypotheses[: self.max_hypotheses], product, profile
            )
            max_directs = self.max_direct_candidates_per_domain * self.max_hypotheses
            direct_urls = list(dict.fromkeys(direct_urls))[:max_directs]
            if direct_urls:
                direct_tasks = [
                    asyncio.create_task(_test_url(url, "direct_product_path"))
                    for url in direct_urls
                ]
                for finished in asyncio.as_completed(direct_tasks):
                    try:
                        cand = await finished
                        if cand is not None:
                            candidates.append(cand)
                            # EARLY STOP: verified manufacturer source with matched MPN
                            if (
                                cand.identity_score >= self.minimum_score
                                and cand.matched_mpn
                                and cand.domain_score >= 1.0
                            ):
                                for t in direct_tasks:
                                    if not t.done():
                                        t.cancel()
                                self.selected_domain = _host(cand.url)
                                self.domains_attempted = tuple(attempted_domains)
                                self.domain_attempt_failure_reasons = domain_failures
                                return sorted(candidates, key=_candidate_rank)
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass

            if not self.circuit_breaker.is_available(domain):
                continue

            # --- B. Targeted Site-Search & Sitemap Discovery ---
            search_tasks: list[asyncio.Task[list[ProductSourceCandidate]]] = []
            search_urls = mfg_strategy.search_urls(
                domain, mpn_hypotheses[: self.max_hypotheses], product, profile
            )
            max_searches = self.max_search_templates_per_domain * self.max_hypotheses
            for search_url in list(dict.fromkeys(search_urls))[:max_searches]:
                search_tasks.append(
                    asyncio.create_task(
                        self._probe_search_url(
                            search_url,
                            domain,
                            profile,
                            product,
                            mfg_strategy,
                            mpn_hypotheses,
                            domains,
                            seen,
                            domain_failures,
                            matcher,
                            _test_url,
                            raw_mpn,
                        )
                    )
                )

            sitemap_candidates = list(self.url_strategy.sitemap_candidates(domain))[
                : self.max_sitemap_paths_per_domain
            ]
            for sitemap_url in sitemap_candidates:
                search_tasks.append(
                    asyncio.create_task(
                        self._probe_sitemap_url(
                            sitemap_url,
                            domain,
                            profile,
                            product,
                            mpn_hypotheses,
                            seen,
                            domain_failures,
                            _test_url,
                        )
                    )
                )

            if search_tasks:
                for search_fut in asyncio.as_completed(search_tasks):
                    try:
                        found_list = await search_fut
                        for found_item in found_list:
                            candidates.append(found_item)
                            if (
                                found_item.identity_score >= self.minimum_score
                                and found_item.matched_mpn
                                and found_item.domain_score >= 1.0
                            ):
                                for st in search_tasks:
                                    if not st.done():
                                        st.cancel()
                                self.selected_domain = _host(found_item.url)
                                self.domains_attempted = tuple(attempted_domains)
                                self.domain_attempt_failure_reasons = domain_failures
                                return sorted(candidates, key=_candidate_rank)
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass

            if domain not in domain_failures:
                domain_failures[domain] = "no_matching_verified_product"

        # ── PHASE 3: Authorized Distributor Secondary Fallback ────────────────
        if not candidates or not any(c.matched_mpn for c in candidates):
            distributor_strategy = AuthorizedDistributorFallbackStrategy()
            distributor_urls = distributor_strategy.generate_urls(
                product, mpn_hypotheses[: self.max_hypotheses]
            )
            dist_tasks = [
                _test_url(
                    dist_url,
                    "distributor_secondary_fallback",
                    allowed_domains=distributor_strategy.domains,
                    is_secondary_distributor=True,
                )
                for dist_url in distributor_urls[:12]
            ]
            if dist_tasks:
                dist_results = await asyncio.gather(*dist_tasks, return_exceptions=True)
                for r in dist_results:
                    if isinstance(r, ProductSourceCandidate):
                        candidates.append(r)

        self.domains_attempted = tuple(attempted_domains)
        self.domain_attempt_failure_reasons = domain_failures
        sorted_candidates = sorted(candidates, key=_candidate_rank)
        self.selected_domain = _host(sorted_candidates[0].url) if sorted_candidates else None
        return sorted_candidates

    async def _probe_search_url(
        self,
        search_url: str,
        domain: str,
        profile: ManufacturerProfile,
        product: ProductTruth,
        mfg_strategy: Any,
        mpn_hypotheses: Any,
        domains: tuple[str, ...],
        seen: set[str],
        domain_failures: dict[str, str],
        matcher: ProductIdentityMatcher,
        test_url_fn: Any,
        raw_mpn: str,
    ) -> list[ProductSourceCandidate]:
        try:
            norm_search_url = canonicalize_url(search_url)
        except ValueError:
            return []
        target_host = _host(norm_search_url)
        if not self.circuit_breaker.is_available(target_host):
            return []
        if norm_search_url in seen:
            return []
        seen.add(norm_search_url)

        source = SourceRecord(
            canonical_url=norm_search_url,
            original_url=norm_search_url,
            source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
            decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
            manufacturer_id=profile.manufacturer_id,
            manufacturer_domain=target_host,
            verified_domains=profile.verified_domains,
            product_id=product.product_id,
        )
        if hasattr(self.fetcher, "fetch_async"):
            fetched = await self.fetcher.fetch_async(source)
        else:
            fetched = await asyncio.to_thread(self.fetcher.fetch, source)

        if fetched.source.retrieval_status is not RetrievalStatus.SUCCESS:
            if (
                fetched.source.retrieval_status == RetrievalStatus.BLOCKED
                or fetched.source.http_status in {403, 429}
            ):
                domain_failures[domain] = "waf_blocked"
            return []

        try:
            doc = HtmlParser().parse(fetched)
        except Exception:
            return []

        found: list[ProductSourceCandidate] = []
        extracted_links: list[str] = []
        for link in doc.links:
            if mfg_strategy.is_product_link(link, mpn_hypotheses, domains):
                extracted_links.append(link.url)

        link_tasks = [
            test_url_fn(ext_url, "site_search_result_link")
            for ext_url in list(dict.fromkeys(extracted_links))[: self.max_search_result_links]
        ]
        if link_tasks:
            link_results = await asyncio.gather(*link_tasks, return_exceptions=True)
            for r in link_results:
                if isinstance(r, ProductSourceCandidate):
                    found.append(r)

        if not found:
            match = matcher.match(product, doc)
            if match.identity_score >= self.minimum_score:
                cand = ProductSourceCandidate(
                    url=norm_search_url,
                    title=doc.title,
                    source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
                    discovery_method="site_search_page_match",
                    evidence_snippet=_snippet(doc, raw_mpn),
                    matched_mpn=match.matched_mpn,
                    matched_manufacturer=match.matched_manufacturer,
                    matched_brand=match.matched_brand,
                    identity_score=match.identity_score,
                    domain_score=1.0,
                    relevance_score=match.relevance_score,
                    mpn_match_type=match.mpn_match_type,
                    raw_mpn_match=match.raw_mpn_match,
                    normalized_mpn_match=match.normalized_mpn_match,
                    transformed_mpn_match=match.transformed_mpn_match,
                    rejection_reason=match.rejection_reason,
                )
                found.append(cand)

        return found

    async def _probe_sitemap_url(
        self,
        sitemap_url: str,
        domain: str,
        profile: ManufacturerProfile,
        product: ProductTruth,
        mpn_hypotheses: Any,
        seen: set[str],
        domain_failures: dict[str, str],
        test_url_fn: Any,
    ) -> list[ProductSourceCandidate]:
        try:
            norm_sm_url = canonicalize_url(sitemap_url)
        except ValueError:
            return []
        target_host = _host(norm_sm_url)
        if not self.circuit_breaker.is_available(target_host):
            return []
        if norm_sm_url in seen:
            return []
        seen.add(norm_sm_url)

        source = SourceRecord(
            canonical_url=norm_sm_url,
            original_url=norm_sm_url,
            source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
            decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
            manufacturer_id=profile.manufacturer_id,
            manufacturer_domain=target_host,
            verified_domains=profile.verified_domains,
            product_id=product.product_id,
        )
        if hasattr(self.fetcher, "fetch_async"):
            fetched = await self.fetcher.fetch_async(source)
        else:
            fetched = await asyncio.to_thread(self.fetcher.fetch, source)

        if fetched.source.retrieval_status is not RetrievalStatus.SUCCESS:
            if (
                fetched.source.retrieval_status == RetrievalStatus.BLOCKED
                or fetched.source.http_status in {403, 429}
            ):
                domain_failures[domain] = "waf_blocked"
            return []

        product_locs, child_sitemaps = _parse_sitemap_xml(fetched.body)
        if not product_locs and child_sitemaps:
            child_tasks = []
            for child_url in child_sitemaps[: self.max_child_sitemaps]:
                try:
                    norm_child_url = canonicalize_url(child_url)
                except ValueError:
                    continue
                child_source = SourceRecord(
                    canonical_url=norm_child_url,
                    original_url=norm_child_url,
                    source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
                    decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                    manufacturer_id=profile.manufacturer_id,
                    manufacturer_domain=_host(norm_child_url),
                    verified_domains=profile.verified_domains,
                    product_id=product.product_id,
                )
                child_tasks.append(
                    self.fetcher.fetch_async(child_source)
                    if hasattr(self.fetcher, "fetch_async")
                    else asyncio.to_thread(self.fetcher.fetch, child_source)
                )
            if child_tasks:
                child_fetched_list = await asyncio.gather(*child_tasks, return_exceptions=True)
                for c_res in child_fetched_list:
                    if (
                        isinstance(c_res, FetchResult)
                        and c_res.source.retrieval_status == RetrievalStatus.SUCCESS
                    ):
                        c_locs, _ = _parse_sitemap_xml(c_res.body)
                        product_locs.extend(c_locs)

        matched_sitemap_urls = []
        for hyp in mpn_hypotheses[: self.max_hypotheses]:
            for loc in product_locs:
                if _sitemap_url_matches_mpn(loc, hyp.value):
                    matched_sitemap_urls.append(loc)

        cand_tasks = [
            test_url_fn(loc, "sitemap_product_match")
            for loc in list(dict.fromkeys(matched_sitemap_urls))[
                : self.max_direct_candidates_per_domain
            ]
        ]
        if cand_tasks:
            cand_results = await asyncio.gather(*cand_tasks, return_exceptions=True)
            return [r for r in cand_results if isinstance(r, ProductSourceCandidate)]
        return []

    def discover(
        self,
        product: ProductTruth,
        profile: ManufacturerProfile,
        candidate_urls: Iterable[str] = (),
    ) -> list[ProductSourceCandidate]:
        """Synchronous wrapper for adiscover."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run, self.adiscover(product, profile, candidate_urls=candidate_urls)
                )
                return future.result()
        else:
            return asyncio.run(self.adiscover(product, profile, candidate_urls=candidate_urls))


def _candidate_rank(item: ProductSourceCandidate) -> tuple[int, float, float, float, str]:
    """Strict authority ranking: Verified Mfg > Candidate Mfg > Mfg Doc/PDF > Distributor."""
    if item.source_kind == SourceKind.DISTRIBUTOR_PRODUCT_PAGE or item.domain_score <= 0.75:
        tier = 1
    elif item.source_kind in {
        SourceKind.MANUFACTURER_TECHNICAL_DOCUMENT,
        SourceKind.MANUFACTURER_MANUAL,
        SourceKind.MANUFACTURER_CATALOG,
    }:
        tier = 2
    elif item.domain_score >= 0.95:
        tier = 4
    else:
        tier = 3
    return (-tier, -item.domain_score, -item.identity_score, -item.relevance_score, item.url)


class ProductIdentityMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_score: float = Field(ge=0, le=1)
    relevance_score: float = Field(ge=0, le=1)
    matched_mpn: bool = False
    mpn_match_type: MpnMatchClassification = MpnMatchClassification.NO_MATCH
    raw_mpn_match: bool = False
    normalized_mpn_match: bool = False
    transformed_mpn_match: bool = False
    transformation_type: str | None = None
    transformation_confidence: float = 0.0
    matched_manufacturer: bool = False
    matched_brand: bool = False
    title_match: bool = False
    description_match: float = 0.0
    classification: str
    rejection_reason: str | None = None


class ProductIdentityMatcher:
    """Explainable identity matching using whole-token normalization and MPN hypotheses.

    Enforces strict identity hierarchy:
      1. RAW_EXACT: Exact raw MPN matched on page (highest confidence).
      2. LOSSLESS_NORMALIZED: Lossless separator/casing variation matched.
      3. VERIFIED_TRANSFORMED: Transformed MPN explicitly supported by manufacturer rule
         + additional product signal.
      4. EXPLORATORY_ONLY: Generic heuristic hypothesis matched -> REJECTED for identity.
      5. NO_MATCH: No MPN matched.
    """

    def match(self, product: ProductTruth, document: object) -> ProductIdentityMatch:
        title = str(getattr(document, "title", "") or "")
        chunks = getattr(document, "chunks", [])
        body_text = " ".join(str(getattr(chunk, "text", "")) for chunk in chunks)
        structured_meta = getattr(document, "structured_metadata", {})
        structured_text = " ".join(_structured_values(structured_meta))
        full_text = " ".join((title, body_text, structured_text))

        raw_mpn = _product_value(product, "manufacturer_part_number") or str(
            product.raw_value("Mfg_Part_Num") or ""
        ).strip()
        manufacturer = _product_value(product, "manufacturer") or str(
            product.raw_value("Part_Manuf") or ""
        ).strip()
        brand = _first_product_value(product, ("brand", "product_family")) or str(
            product.raw_value("Unilog_Brand")
            or product.raw_value("E1_Brand")
            or product.raw_value("DIB_Brand")
            or ""
        ).strip()

        # Generate hypotheses with manufacturer and brand context
        normalizer = MpnNormalizer()
        mfg_hint = f"{manufacturer} {brand}".strip()
        hypotheses = normalizer.normalize(raw_mpn, manufacturer_hint=mfg_hint)

        # Check whole-token matching for each hypothesis
        raw_match = bool(raw_mpn and _is_literal_token_match(raw_mpn, full_text))
        normalized_match = False
        verified_transform_match = False
        exploratory_match = False
        best_transform_type: str | None = None
        best_transform_conf: float = 0.0

        for hyp in hypotheses:
            if _is_exact_token_match(hyp.value, full_text):
                if hyp.hypothesis_type == MpnHypothesisType.RAW:
                    if _is_literal_token_match(hyp.value, full_text):
                        raw_match = True
                    else:
                        normalized_match = True
                elif (
                    hyp.is_lossless
                    or hyp.hypothesis_type == MpnHypothesisType.LOSSLESS_NORMALIZED
                    or hyp.hypothesis_type == MpnHypothesisType.ALPHANUMERIC_COMPACT
                ):
                    normalized_match = True
                elif (
                    hyp.identity_eligible
                    or hyp.hypothesis_type == MpnHypothesisType.VERIFIED_MANUFACTURER_TRANSFORM
                ):
                    verified_transform_match = True
                    if hyp.confidence > best_transform_conf:
                        best_transform_conf = hyp.confidence
                        best_transform_type = hyp.hypothesis_type.value
                else:
                    exploratory_match = True
                    if hyp.confidence > best_transform_conf:
                        best_transform_conf = hyp.confidence
                        best_transform_type = hyp.hypothesis_type.value

        # Determine MPN match classification
        if raw_match:
            mpn_match_type = MpnMatchClassification.RAW_EXACT
            mpn_conf = 1.0
            is_mpn_verified = True
        elif normalized_match:
            mpn_match_type = MpnMatchClassification.LOSSLESS_NORMALIZED
            mpn_conf = 0.95
            is_mpn_verified = True
        elif verified_transform_match:
            mpn_match_type = MpnMatchClassification.VERIFIED_TRANSFORMED
            mpn_conf = 0.85
            is_mpn_verified = True
        elif exploratory_match:
            mpn_match_type = MpnMatchClassification.EXPLORATORY_ONLY
            mpn_conf = 0.20
            is_mpn_verified = False
        else:
            mpn_match_type = MpnMatchClassification.NO_MATCH
            mpn_conf = 0.0
            is_mpn_verified = False

        # Check manufacturer, brand, title, description consistency
        matched_manufacturer = _identity_present(_base_identity(manufacturer), full_text)
        matched_brand = bool(brand and _identity_present(brand, full_text))

        # Title match requires raw, normalized, or verified transformed MPN in title
        title_hypotheses = [h for h in hypotheses if (h.is_lossless or h.identity_eligible)]
        title_match = bool(
            title_hypotheses
            and any(_is_exact_token_match(h.value, title) for h in title_hypotheses)
        )
        desc_overlap = _description_overlap(product, full_text.casefold())

        # Base score calculation with manufacturer/brand context
        has_mfg_or_brand = matched_manufacturer or matched_brand
        both_mfg_and_brand = matched_manufacturer and matched_brand
        score = (
            0.50 * mpn_conf
            + 0.20 * (1.0 if has_mfg_or_brand else 0.0)
            + 0.10 * (1.0 if both_mfg_and_brand else 0.0)
            + 0.10 * (1.0 if title_match else 0.0)
            + 0.10 * desc_overlap
        )

        rejection_reason: str | None = None
        classification: str

        if mpn_match_type in {
            MpnMatchClassification.RAW_EXACT,
            MpnMatchClassification.LOSSLESS_NORMALIZED,
        }:
            # CASE 1 & CASE 2: RAW_EXACT or LOSSLESS_NORMALIZED
            has_context = (
                matched_manufacturer
                or matched_brand
                or desc_overlap >= 0.15
                or title_match
            )
            if has_context and score >= 0.8:
                classification = "EXACT_MATCH"
            elif has_context and score >= 0.6:
                classification = "STRONG_MATCH"
            elif has_context:
                classification = "WEAK_MATCH"
            else:
                classification = "WEAK_MATCH"
                rejection_reason = "MANUFACTURER_BRAND_MISMATCH"
                score = min(score, 0.55)

        elif mpn_match_type == MpnMatchClassification.VERIFIED_TRANSFORMED:
            # CASE 3: VERIFIED_TRANSFORMED
            mfg_or_brand_matched = matched_manufacturer or matched_brand
            has_additional_signal = (
                (matched_manufacturer and matched_brand) or title_match or (desc_overlap >= 0.15)
            )
            if mfg_or_brand_matched and has_additional_signal and score >= 0.6:
                classification = "STRONG_MATCH"
            elif not mfg_or_brand_matched:
                classification = "WEAK_MATCH"
                rejection_reason = "TRANSFORMED_MPN_REQUIRES_MANUFACTURER_MATCH"
                score = min(score, 0.55)
            else:
                classification = "WEAK_MATCH"
                rejection_reason = "TRANSFORMED_MPN_REQUIRES_ADDITIONAL_SIGNAL"
                score = min(score, 0.55)

        elif mpn_match_type == MpnMatchClassification.EXPLORATORY_ONLY:
            # CASE 4: EXPLORATORY_ONLY (never accepted as verified identity)
            classification = "WEAK_MATCH"
            rejection_reason = "EXPLORATORY_MPN_UNVERIFIED"
            score = min(score, 0.45)

        else:
            # CASE 5, 6, 7: NO MPN MATCH
            classification = "WEAK_MATCH" if score >= 0.35 else "MISMATCH"
            rejection_reason = "MPN_NOT_FOUND"

        return ProductIdentityMatch(
            identity_score=round(score, 3),
            relevance_score=round(score, 3),
            matched_mpn=is_mpn_verified and (rejection_reason is None),
            mpn_match_type=mpn_match_type,
            raw_mpn_match=raw_match,
            normalized_mpn_match=normalized_match,
            transformed_mpn_match=verified_transform_match or exploratory_match,
            transformation_type=best_transform_type,
            transformation_confidence=best_transform_conf,
            matched_manufacturer=matched_manufacturer,
            matched_brand=matched_brand,
            title_match=title_match,
            description_match=round(desc_overlap, 3),
            classification=classification,
            rejection_reason=rejection_reason,
        )


class DeterministicUrlStrategy:
    """Generate candidate product URLs from known patterns without any HTTP calls."""

    _product_prefixes = (
        "products",
        "product",
        "p",
        "catalog",
        "items",
        "item",
        "tools",
        "en/p/owner-center/product-support",
        "owner-center/product-support",
        "Owner-Center/Product-Support",
        "support",
        "product-support",
        "owners",
        "docs",
        "documents",
        "manuals",
        "specs",
    )
    _site_search_patterns = (
        "/search?q={mpn}",
        "/?s={mpn}",
        "/?s={mpn}&post_type=product",
        "/search?query={mpn}",
        "/catalogsearch/result/?q={mpn}",
        "/search/{mpn}",
        "/smartsearchresults?searchtext={mpn}",
        "/search?searchTerm={mpn}",
        "/search?keywords={mpn}",
    )
    _sitemap_paths = (
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/product-sitemap.xml",
        "/products-sitemap.xml",
        "/sitemap/products.xml",
    )

    def product_url_candidates(self, domain: str, mpn: str) -> tuple[str, ...]:
        if not mpn or not mpn.strip():
            return ()
        origin = _origin(domain)
        safe_mpn = re.sub(r"[^A-Za-z0-9._-]+", "-", mpn.strip()).strip("-")
        if not safe_mpn:
            return ()
        values: list[str] = []
        for prefix in self._product_prefixes:
            with contextlib.suppress(ValueError):
                values.append(canonicalize_url(f"{origin}/{prefix}/{safe_mpn}"))
        with contextlib.suppress(ValueError):
            values.append(canonicalize_url(f"{origin}/{safe_mpn}"))
        for pattern in self._site_search_patterns:
            with contextlib.suppress(ValueError):
                values.append(canonicalize_url(f"{origin}{pattern.format(mpn=safe_mpn)}"))
        return tuple(dict.fromkeys(values))

    def direct_product_paths(self, domain: str, mpn: str) -> tuple[str, ...]:
        if not mpn or not mpn.strip():
            return ()
        origin = _origin(domain)
        safe_mpn = re.sub(r"[^A-Za-z0-9._-]+", "-", mpn.strip()).strip("-")
        if not safe_mpn:
            return ()
        values: list[str] = []
        for prefix in self._product_prefixes:
            with contextlib.suppress(ValueError):
                values.append(canonicalize_url(f"{origin}/{prefix}/{safe_mpn}"))
        with contextlib.suppress(ValueError):
            values.append(canonicalize_url(f"{origin}/{safe_mpn}"))
        return tuple(dict.fromkeys(values))

    def site_search_candidates(self, domain: str, mpn: str) -> tuple[str, ...]:
        if not mpn or not mpn.strip():
            return ()
        origin = _origin(domain)
        safe_mpn = re.sub(r"[^A-Za-z0-9._-]+", "-", mpn.strip()).strip("-")
        if not safe_mpn:
            return ()
        values: list[str] = []
        for pattern in self._site_search_patterns:
            with contextlib.suppress(ValueError):
                values.append(canonicalize_url(f"{origin}{pattern.format(mpn=safe_mpn)}"))
        return tuple(dict.fromkeys(values))

    def sitemap_candidates(self, domain: str) -> tuple[str, ...]:
        origin = _origin(domain)
        values: list[str] = []
        for path in self._sitemap_paths:
            with contextlib.suppress(ValueError):
                values.append(canonicalize_url(f"{origin}{path}"))
        return tuple(dict.fromkeys(values))

    def all_candidates(self, domains: tuple[str, ...], mpn: str | None) -> tuple[str, ...]:
        if not mpn:
            return ()
        values: list[str] = []
        for domain in domains:
            values.extend(self.product_url_candidates(domain, mpn))
        return tuple(dict.fromkeys(values))


def _strategy_names_for(domains: tuple[str, ...], mpn: str | None) -> tuple[str, ...]:
    if not mpn or not domains:
        return ()
    return (
        "deterministic_direct_paths",
        "deterministic_site_search",
        "deterministic_sitemap",
    )


def _parse_sitemap_xml(
    body: bytes, max_entries: int = 5000
) -> tuple[list[str], list[str]]:
    """Parse sitemap XML safely without external entity expansion."""
    product_locs: list[str] = []
    child_sitemaps: list[str] = []
    if not body:
        return product_locs, child_sitemaps
    try:
        sample = body[: 10 * 1024 * 1024]
        root = ET.fromstring(sample)
        tag = root.tag.split("}")[-1].casefold()
        if tag == "urlset":
            for elem in root:
                if len(product_locs) >= max_entries:
                    break
                elem_tag = elem.tag.split("}")[-1].casefold()
                if elem_tag == "url":
                    for child in elem:
                        child_tag = child.tag.split("}")[-1].casefold()
                        if child_tag == "loc" and child.text:
                            loc = child.text.strip()
                            if loc:
                                product_locs.append(loc)
        elif tag == "sitemapindex":
            for elem in root:
                if len(child_sitemaps) >= max_entries:
                    break
                elem_tag = elem.tag.split("}")[-1].casefold()
                if elem_tag == "sitemap":
                    for child in elem:
                        child_tag = child.tag.split("}")[-1].casefold()
                        if child_tag == "loc" and child.text:
                            loc = child.text.strip()
                            if loc:
                                child_sitemaps.append(loc)
    except Exception:
        pass
    return product_locs, child_sitemaps


def _sitemap_url_matches_mpn(url: str, mpn: str) -> bool:
    """Check whether a sitemap URL corresponds to the target MPN using strict token matching."""
    if not mpn or not url:
        return False
    normalized_mpn = _identity_key(mpn)
    if not normalized_mpn:
        return False
    path = urlsplit(url).path
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]*", path)
    if any(_identity_key(token) == normalized_mpn for token in tokens):
        return True
    segments = re.split(r"[/._]", path)
    if any(_identity_key(seg) == normalized_mpn for seg in segments):
        return True
    safe_mpn = re.sub(r"[^a-z0-9]+", "-", mpn.casefold()).strip("-")
    return bool(safe_mpn and safe_mpn in path.casefold())


def _is_search_result_product_link(
    link: DocumentLink,
    mpn_hypotheses: Iterable[MpnHypothesis],
    domains: Iterable[str],
    profile: ManufacturerRetrievalProfile | None = None,
) -> bool:
    """Determine whether a link extracted from a site-search results page leads to a product."""
    if not any(_same_or_subdomain(_host(link.url), domain) for domain in domains):
        return False
    text = f"{link.anchor_text} {link.url}".casefold()
    if any(_identity_present(hyp.value, text) for hyp in mpn_hypotheses):
        return True
    path = urlsplit(link.url).path.casefold()
    product_markers = (
        "/product/",
        "/products/",
        "/p/",
        "/catalog/",
        "/item/",
        "/items/",
        "/tools/",
        "/detail",
        "/pd/",
        "/pdp",
        "/part-number/",
        "/product-id/",
        "/learningitem/",
        "/owner-center/",
        "/product-support/",
        "/support/",
        "/owners/",
        "/docs/",
        "/documents/",
        "/specs/",
        ".pdf",
    )
    if any(marker in path for marker in product_markers):
        return True
    if profile:
        for marker in profile.product_link_patterns:
            if marker in path:
                return True
    return False


def _structured_values(value: object) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            is_metadata_key = key.casefold() in {
                "mpn",
                "manufacturer",
                "brand",
                "name",
                "description",
                "model",
            }
            if is_metadata_key or key == "@graph":
                values.extend(_structured_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_structured_values(child))
    elif value is not None:
        if isinstance(value, dict):
            values.extend(_structured_values(value))
        else:
            values.append(str(value))
    return values


def _is_literal_token_match(target: str, text: str) -> bool:
    """Check whether target appears literally as a standalone compound token in text."""
    if not target or not text:
        return False
    target_clean = target.strip()
    if not target_clean:
        return False
    target_lower = target_clean.casefold()
    compound_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]*", text)
    for token in compound_tokens:
        clean_tok = token.rstrip(".,;:!?'\"").casefold()
        if clean_tok == target_lower:
            return True
    return False


def _is_exact_token_match(target: str, text: str) -> bool:
    """Check whether target appears as a complete, bounded token or separator-variant in text."""
    if not target or not text:
        return False
    target_clean = target.strip()
    if not target_clean:
        return False
    # 1. Literal match first
    if _is_literal_token_match(target_clean, text):
        return True
    target_key = _identity_key(target_clean)
    if not target_key:
        return False

    # 1. Compound tokens (e.g. '49-94-0013', 'DCB518ASTS06G', 'ABC-123')
    compound_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]*", text)
    for token in compound_tokens:
        if _identity_key(token) == target_key:
            return True

    # 2. If target has separators (e.g. '49-94-0013'), match flexible whitespace/punctuation
    parts = [re.escape(p) for p in re.split(r"[-_\s/.]+", target_clean) if p]
    if len(parts) > 1:
        pattern = r"(?<![A-Za-z0-9])" + r"[-_\s/.]+".join(parts) + r"(?![A-Za-z0-9])"
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


def _identity_present(value: str | None, text: str) -> bool:
    if not value:
        return False
    wanted = _identity_key(value)
    if not wanted:
        return False
    token_keys = {
        _identity_key(token)
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]*", text)
    }
    if wanted in token_keys:
        return True
    words = [_identity_key(w) for w in value.split() if len(_identity_key(w)) >= 3]
    stopwords = {
        "inc", "llc", "corp", "company", "co", "ltd", "tool", "tools",
        "supply", "dealer", "accessory", "accessories", "industrial", "abrasives",
    }
    meaningful = [w for w in words if w not in stopwords]
    return bool(meaningful and any(w in token_keys for w in meaningful))


def _identity_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _product_value(product: ProductTruth, field: str) -> str | None:
    value = getattr(product.identity, field, None)
    if value is None:
        return None
    return str(value.normalized_value or value.raw_value or "").strip() or None


def _first_product_value(product: ProductTruth, fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = _product_value(product, field)
        if value:
            return value
    return None


def _base_identity(value: str) -> str:
    return value.split("(", 1)[0].strip()


def _description_overlap(product: ProductTruth, normalized: str) -> float:
    description = str(product.raw_value("Part_Desc") or "")
    words = [word.casefold() for word in description.split() if len(word) >= 4]
    if not words:
        return 0.0
    return min(1.0, sum(word in normalized for word in words) / len(words))


def _snippet(document: object, mpn: str | None) -> str:
    chunks = getattr(document, "chunks", [])
    for chunk in chunks:
        text = str(getattr(chunk, "text", ""))
        if not mpn or _identity_present(mpn, text):
            return text[:500]
    return str(getattr(chunks[0], "text", ""))[:500] if chunks else ""


def _source_kind(url: str) -> SourceKind:
    suffix = PurePosixPath(urlsplit(url).path.casefold()).suffix
    if suffix == ".pdf":
        return SourceKind.MANUFACTURER_TECHNICAL_DOCUMENT
    return SourceKind.MANUFACTURER_PRODUCT_PAGE


def _origin(value: str) -> str:
    url = value if "://" in value else f"https://{value}/"
    parts = urlsplit(canonicalize_url(url))
    return f"{parts.scheme}://{parts.netloc}"


def _host(value: str) -> str:
    return (urlsplit(value if "://" in value else f"//{value}").hostname or "").casefold()


def _same_or_subdomain(host: str, parent: str) -> bool:
    return host == parent or host.endswith("." + parent)
