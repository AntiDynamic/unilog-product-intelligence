"""Deterministic exact-product source discovery after manufacturer-domain discovery."""

from __future__ import annotations

import contextlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.domain.truth import ProductTruth
from unilog_product_intelligence.retrieval.mpn_normalizer import MpnHypothesis, MpnNormalizer

from .core import (
    DocumentLink,
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
        domains=("www.3m.com", "3m.com"),
        search_url_templates=(
            "https://www.3m.com/3M/en_US/search/?q={mpn}",
            "https://www.3m.com/search?q={mpn}",
            "https://www.3m.com/en_US/search/results?search={mpn}",
        ),
        direct_path_templates=(
            "https://www.3m.com/3M/en_US/p/d/{mpn}/",
            "https://www.3m.com/p/d/{mpn}/",
            "https://www.3m.com/products/{mpn}",
        ),
        product_link_patterns=("/p/d/", "/products/"),
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
)


def _get_retrieval_profile(domains: tuple[str, ...]) -> ManufacturerRetrievalProfile | None:
    for profile in _RETRIEVAL_PROFILES:
        if any(any(_same_or_subdomain(d, prof_d) for prof_d in profile.domains) for d in domains):
            return profile
    return None


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


class ProductSourceDiscoveryService:
    """Find exact product sources with ranked, bounded, iterative strategy execution.

    Executes unified deterministic retrieval strategies in strict priority order:
      1. Candidate URLs supplied by caller or prior steps
      2. Direct product URL path patterns (testing all MPN hypotheses)
      3. Site-search endpoints (fetches search page, extracts product links, validates)
      4. Sitemap discovery (fetches sitemap.xml, extracts matching product URLs)

    Short-circuits immediately upon discovering an exact high-confidence product match.
    """

    def __init__(
        self,
        fetcher: SourceFetcher,
        minimum_score: float = 0.6,
        max_candidates: int = 64,
        url_strategy: DeterministicUrlStrategy | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.minimum_score = minimum_score
        self.max_candidates = max_candidates
        self.url_strategy = url_strategy or DeterministicUrlStrategy()

    def discover(
        self,
        product: ProductTruth,
        profile: ManufacturerProfile,
        candidate_urls: Iterable[str] = (),
    ) -> list[ProductSourceCandidate]:
        raw_mpn = _product_value(product, "manufacturer_part_number") or str(
            product.raw_value("Mfg_Part_Num") or ""
        ).strip()
        normalizer = MpnNormalizer()
        mpn_hypotheses = normalizer.normalize(raw_mpn)
        domains = tuple(_host(domain) for domain in profile.verified_domains)
        if not domains:
            return []

        retrieval_profile = _get_retrieval_profile(domains)
        seen: set[str] = set()
        candidates: list[ProductSourceCandidate] = []
        matcher = ProductIdentityMatcher()

        def test_product_url(url: str, method: str) -> ProductSourceCandidate | None:
            try:
                norm_url = canonicalize_url(url)
            except ValueError:
                return None
            if norm_url in seen or not any(_same_or_subdomain(_host(norm_url), d) for d in domains):
                return None
            seen.add(norm_url)

            source_kind = _source_kind(norm_url)
            source = SourceRecord(
                canonical_url=norm_url,
                original_url=norm_url,
                source_kind=source_kind,
                decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                manufacturer_id=profile.manufacturer_id,
                manufacturer_domain=_host(norm_url),
                product_id=product.product_id,
            )
            fetched = self.fetcher.fetch(source)
            if fetched.source.retrieval_status is not RetrievalStatus.SUCCESS:
                return None

            content_type = fetched.source.content_type or ""
            valid_types = {"text/html", "text/plain", "application/pdf", "application/json"}
            if content_type not in valid_types:
                return None

            parser = PdfParser() if content_type == "application/pdf" else HtmlParser()
            document = parser.parse(fetched)
            match = matcher.match(product, document)
            if match.identity_score >= self.minimum_score:
                canonical = document.canonical_url or norm_url
                if not any(_same_or_subdomain(_host(canonical), d) for d in domains):
                    canonical = norm_url
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
                    domain_score=1.0,
                    relevance_score=match.relevance_score,
                )
                return cand
            return None

        # ── PHASE 1: Caller-supplied Candidate URLs ───────────────────────────
        for cand_url in list(candidate_urls)[:2]:
            cand = test_product_url(cand_url, "supplied_candidate_url")
            if cand:
                candidates.append(cand)
                if cand.identity_score >= self.minimum_score and cand.matched_mpn:
                    return candidates

        # ── PHASE 2: Direct Product Path Patterns (testing primary domain) ────
        primary_domains = profile.verified_domains[:1] if profile.verified_domains else ()
        for domain in primary_domains:
            for hyp in mpn_hypotheses[:2]:
                direct_urls = list(self.url_strategy.direct_product_paths(domain, hyp.value))[:2]
                for direct_url in direct_urls:
                    cand = test_product_url(direct_url, f"direct_pattern_{hyp.hypothesis_type}")
                    if cand:
                        candidates.append(cand)
                        if cand.identity_score >= self.minimum_score and cand.matched_mpn:
                            return candidates
                if retrieval_profile:
                    for tmpl in retrieval_profile.direct_path_templates[:2]:
                        url_cand = tmpl.format(mpn=hyp.value)
                        cand = test_product_url(url_cand, f"profile_direct_{hyp.hypothesis_type}")
                        if cand:
                            candidates.append(cand)
                            if cand.identity_score >= self.minimum_score and cand.matched_mpn:
                                return candidates

        # ── PHASE 3: Targeted Site-Search Probe & Link Extraction ─────────────
        search_urls: list[str] = []
        for domain in primary_domains:
            for hyp in mpn_hypotheses[:1]:
                if retrieval_profile and retrieval_profile.search_url_templates:
                    search_urls.append(
                        retrieval_profile.search_url_templates[0].format(mpn=hyp.value)
                    )
                else:
                    candidates_found = list(
                        self.url_strategy.site_search_candidates(domain, hyp.value)
                    )
                    if candidates_found:
                        search_urls.append(candidates_found[0])

        for search_url in list(dict.fromkeys(search_urls))[:1]:
            try:
                norm_search_url = canonicalize_url(search_url)
            except ValueError:
                continue
            if norm_search_url in seen:
                continue
            seen.add(norm_search_url)

            source = SourceRecord(
                canonical_url=norm_search_url,
                original_url=norm_search_url,
                source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
                decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                manufacturer_id=profile.manufacturer_id,
                manufacturer_domain=_host(norm_search_url),
                product_id=product.product_id,
            )
            fetched = self.fetcher.fetch(source)
            if fetched.source.retrieval_status is not RetrievalStatus.SUCCESS:
                continue

            parser = HtmlParser()
            doc = parser.parse(fetched)

            # Check if search page itself is a direct product match
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
                )
                candidates.append(cand)
                if cand.identity_score >= self.minimum_score and cand.matched_mpn:
                    return candidates

            # Extract product candidate links from the search results
            extracted_links: list[str] = []
            for link in doc.links:
                if _is_search_result_product_link(
                    link, mpn_hypotheses, domains, retrieval_profile
                ):
                    extracted_links.append(link.url)

            # Test top extracted links (up to 3 per search query)
            for ext_url in list(dict.fromkeys(extracted_links))[:3]:
                cand = test_product_url(ext_url, "site_search_result_link")
                if cand:
                    candidates.append(cand)
                    if cand.identity_score >= self.minimum_score and cand.matched_mpn:
                        return candidates

        # ── PHASE 4: Sitemap Filtering ────────────────────────────────────────
        for domain in primary_domains:
            sitemap_candidates = list(self.url_strategy.sitemap_candidates(domain))
            for sitemap_url in sitemap_candidates[:1]:
                try:
                    norm_sm_url = canonicalize_url(sitemap_url)
                except ValueError:
                    continue
                if norm_sm_url in seen:
                    continue
                seen.add(norm_sm_url)

                source = SourceRecord(
                    canonical_url=norm_sm_url,
                    original_url=norm_sm_url,
                    source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
                    decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
                    manufacturer_id=profile.manufacturer_id,
                    manufacturer_domain=_host(norm_sm_url),
                    product_id=product.product_id,
                )
                fetched = self.fetcher.fetch(source)
                if fetched.source.retrieval_status is not RetrievalStatus.SUCCESS:
                    continue
                product_locs, child_sitemaps = _parse_sitemap_xml(fetched.body)
                if not product_locs and child_sitemaps:
                    for child_url in child_sitemaps[:3]:
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
                            product_id=product.product_id,
                        )
                        child_fetched = self.fetcher.fetch(child_source)
                        if child_fetched.source.retrieval_status is RetrievalStatus.SUCCESS:
                            c_locs, _ = _parse_sitemap_xml(child_fetched.body)
                            product_locs.extend(c_locs)

                for hyp in mpn_hypotheses:
                    matched_urls = [
                        loc for loc in product_locs if _sitemap_url_matches_mpn(loc, hyp.value)
                    ]
                    for loc in matched_urls[:2]:
                        cand = test_product_url(loc, "sitemap_product_match")
                        if cand:
                            candidates.append(cand)
                            if cand.identity_score >= self.minimum_score and cand.matched_mpn:
                                return candidates

        return sorted(
            candidates,
            key=lambda item: (-item.identity_score, -item.relevance_score, item.url),
        )


class ProductIdentityMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_score: float = Field(ge=0, le=1)
    relevance_score: float = Field(ge=0, le=1)
    matched_mpn: bool = False
    matched_manufacturer: bool = False
    matched_brand: bool = False
    classification: str


class ProductIdentityMatcher:
    """Explainable identity matching using whole-token normalization and MPN hypotheses."""

    def match(self, product: ProductTruth, document: object) -> ProductIdentityMatch:
        title = str(getattr(document, "title", "") or "")
        chunks = getattr(document, "chunks", [])
        body_text = " ".join(str(getattr(chunk, "text", "")) for chunk in chunks)
        metadata_text = " ".join(_structured_values(getattr(document, "structured_metadata", {})))
        text = " ".join((title, body_text, metadata_text))
        raw_mpn = _product_value(product, "manufacturer_part_number") or str(
            product.raw_value("Mfg_Part_Num") or ""
        )
        manufacturer = _product_value(product, "manufacturer") or str(
            product.raw_value("Part_Manuf") or ""
        )
        brand = _first_product_value(product, ("brand", "product_family"))

        normalizer = MpnNormalizer()
        hypotheses = normalizer.normalize(raw_mpn)

        best_mpn_match = False
        mpn_conf = 0.0
        for hyp in hypotheses:
            if _identity_present(hyp.value, text):
                best_mpn_match = True
                if hyp.confidence > mpn_conf:
                    mpn_conf = hyp.confidence

        matched_manufacturer = _identity_present(_base_identity(manufacturer), text)
        matched_brand = _identity_present(brand, text)
        title_match = bool(raw_mpn and any(_identity_present(h.value, title) for h in hypotheses))

        score = (
            0.50 * (mpn_conf if best_mpn_match else 0.0)
            + 0.20 * matched_manufacturer
            + 0.10 * matched_brand
            + 0.10 * title_match
            + 0.10 * _description_overlap(product, text.casefold())
        )
        classification = (
            "EXACT_MATCH"
            if score >= 0.8 and best_mpn_match
            else "STRONG_MATCH"
            if score >= 0.6 and best_mpn_match
            else "WEAK_MATCH"
            if score >= 0.35
            else "MISMATCH"
        )
        return ProductIdentityMatch(
            identity_score=round(score, 3),
            relevance_score=round(score, 3),
            matched_mpn=best_mpn_match,
            matched_manufacturer=matched_manufacturer,
            matched_brand=matched_brand,
            classification=classification,
        )


class DeterministicUrlStrategy:
    """Generate candidate product URLs from known patterns without any HTTP calls."""

    _product_prefixes = ("products", "product", "p", "catalog", "items", "item", "tools")
    _site_search_patterns = (
        "/search?q={mpn}",
        "/search?query={mpn}",
        "/search?term={mpn}",
        "/search?keywords={mpn}",
        "/search/{mpn}",
        "/catalogsearch/result?q={mpn}",
        "/?s={mpn}",
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
