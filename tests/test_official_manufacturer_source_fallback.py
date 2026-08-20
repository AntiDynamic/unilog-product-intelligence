"""Official manufacturer source retrieval, document discovery, and fallback policy tests."""

from __future__ import annotations

import zlib

from unilog_product_intelligence.application.brand_resolver import BrandManufacturerResolver
from unilog_product_intelligence.domain.truth import (
    ProductTruth,
    RawInputField,
)
from unilog_product_intelligence.retrieval.core import (
    CacheStatus,
    DomainResolver,
    FetchResult,
    ManufacturerProfile,
    RetrievalStatus,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourcePolicy,
    SourceRecord,
    SourceVerifier,
)
from unilog_product_intelligence.retrieval.source_discovery import (
    ProductSourceCandidate,
    ProductSourceDiscoveryService,
    _candidate_rank,
)


def _make_product(
    mpn: str = "PDSH4816AF",
    mfg: str = "Appliance Dealers Cooperative (APPDE)",
    brand: str = "Frigidaire",
    desc: str = "Frigidaire 24 Built-In Dishwasher",
    product_id: str = "test-prod-1",
) -> ProductTruth:
    return ProductTruth(
        product_id=product_id,
        raw_inputs=(
            RawInputField(field_name="Mfg_Part_Num", raw_value=mpn, source_id="input-1"),
            RawInputField(field_name="Part_Manuf", raw_value=mfg, source_id="input-1"),
            RawInputField(field_name="Unilog_Brand", raw_value=brand, source_id="input-1"),
            RawInputField(field_name="Part_Desc", raw_value=desc, source_id="input-1"),
        ),
    )


class MockFetcher(SourceFetcher):
    def __init__(
        self,
        html_map: dict[str, bytes] | None = None,
        content_type_map: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.html_map = html_map or {}
        self.content_type_map = content_type_map or {}

    def fetch(self, source: SourceRecord, refresh: bool = False) -> FetchResult:
        body = self.html_map.get(source.canonical_url)
        content_type = self.content_type_map.get(source.canonical_url, "text/html")
        if body is not None:
            return FetchResult(
                source=source.model_copy(
                    update={
                        "retrieval_status": RetrievalStatus.SUCCESS,
                        "http_status": 200,
                        "content_type": content_type,
                    }
                ),
                body=body,
                cache_status=CacheStatus.HIT,
            )
        return FetchResult(
            source=source.model_copy(
                update={"retrieval_status": RetrievalStatus.FAILED, "http_status": 404}
            ),
            error="http_404",
            cache_status=CacheStatus.MISS,
        )


# ── TEST 1: Manufacturer product page direct route available ─────────────────
def test_1_manufacturer_product_page_selected() -> None:
    product = _make_product(mpn="PDSH4816AF", mfg="Frigidaire", brand="Frigidaire")
    direct_url = "https://frigidaire.com/products/PDSH4816AF"
    html = b"""
    <html>
      <head><title>Frigidaire PDSH4816AF Built-In Dishwasher</title></head>
      <body>
        <h1>Frigidaire PDSH4816AF</h1>
        <p>Model: PDSH4816AF</p>
      </body>
    </html>
    """
    fetcher = MockFetcher({direct_url: html})
    service = ProductSourceDiscoveryService(fetcher=fetcher)
    profile = ManufacturerProfile(
        manufacturer_id="frigidaire",
        canonical_name="Frigidaire",
        verified_domains=("frigidaire.com",),
    )
    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    best = candidates[0]
    assert best.url == direct_url
    assert best.matched_mpn is True
    assert best.domain_score == 1.0
    assert best.source_kind == SourceKind.MANUFACTURER_PRODUCT_PAGE


# ── TEST 2: Direct route failed, support page available ──────────────────────
def test_2_direct_failed_support_page_available() -> None:
    product = _make_product(mpn="PDSH4816AF", mfg="Frigidaire", brand="Frigidaire")
    support_url = "https://www.frigidaire.com/en/p/owner-center/product-support/PDSH4816AF"
    support_html = b"""
    <html>
      <head><title>PDSH4816AF Product Support | Frigidaire</title></head>
      <body>
        <h1>Frigidaire PDSH4816AF Support & Manuals</h1>
        <p>Model Number: PDSH4816AF</p>
      </body>
    </html>
    """
    fetcher = MockFetcher({support_url: support_html})
    service = ProductSourceDiscoveryService(fetcher=fetcher)
    profile = ManufacturerProfile(
        manufacturer_id="frigidaire",
        canonical_name="Frigidaire",
        verified_domains=("frigidaire.com", "www.frigidaire.com"),
    )
    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    best = candidates[0]
    assert "owner-center/product-support/PDSH4816AF" in best.url
    assert best.matched_mpn is True
    assert best.domain_score == 1.0


# ── TEST 3: Direct + support failed, sitemap available ───────────────────────
def test_3_direct_and_support_failed_sitemap_available() -> None:
    product = _make_product(mpn="PDSH4816AF", mfg="Frigidaire", brand="Frigidaire")
    sitemap_url = "https://frigidaire.com/sitemap.xml"
    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://frigidaire.com/kitchen/dishwashers/pdsh4816af</loc>
      </url>
    </urlset>
    """
    matched_product_url = "https://frigidaire.com/kitchen/dishwashers/pdsh4816af"
    matched_html = b"""
    <html>
      <head><title>Frigidaire PDSH4816AF Dishwasher</title></head>
      <body><h1>PDSH4816AF</h1></body>
    </html>
    """
    fetcher = MockFetcher(
        {
            sitemap_url: sitemap_xml,
            matched_product_url: matched_html,
        },
        {
            sitemap_url: "text/xml",
            matched_product_url: "text/html",
        },
    )
    service = ProductSourceDiscoveryService(fetcher=fetcher)
    profile = ManufacturerProfile(
        manufacturer_id="frigidaire",
        canonical_name="Frigidaire",
        verified_domains=("frigidaire.com",),
    )
    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    best = candidates[0]
    assert "pdsh4816af" in best.url
    assert best.matched_mpn is True
    assert best.domain_score == 1.0


# ── TEST 4: Document fallback (PDF) ──────────────────────────────────────────
def test_4_document_fallback_pdf() -> None:
    product = _make_product(mpn="WDTS7024RZ", mfg="Whirlpool", brand="Whirlpool")
    pdf_url = "https://learnwhirlpool.com/docs/WDTS7024RZ_spec_sheet.pdf"

    stream_content = b"BT /F1 12 Tf (Whirlpool WDTS7024RZ Spec Sheet) Tj (Voltage: 120V) Tj ET"
    compressed = zlib.compress(stream_content)
    pdf_body = (
        b"%PDF-1.4\n1 0 obj\n<< /Length "
        + str(len(compressed)).encode()
        + b" /Filter /FlateDecode >>\nstream\n"
        + compressed
        + b"\nendstream\nendobj\n%%EOF"
    )

    fetcher = MockFetcher(
        {pdf_url: pdf_body},
        {pdf_url: "application/pdf"},
    )
    service = ProductSourceDiscoveryService(fetcher=fetcher)
    profile = ManufacturerProfile(
        manufacturer_id="whirlpool",
        canonical_name="Whirlpool",
        verified_domains=("learnwhirlpool.com",),
    )
    candidates = service.discover(product, profile, candidate_urls=[pdf_url])

    assert len(candidates) > 0
    best = candidates[0]
    assert best.url == pdf_url
    assert best.source_kind == SourceKind.MANUFACTURER_TECHNICAL_DOCUMENT
    assert best.matched_mpn is True


# ── TEST 5: Unrelated manufacturer PDF rejected ──────────────────────────────
def test_5_unrelated_manufacturer_pdf_rejected() -> None:
    product = _make_product(mpn="WDTS7024RZ", mfg="Whirlpool", brand="Whirlpool")
    unrelated_pdf_url = "https://learnwhirlpool.com/docs/OTHER_MODEL_spec.pdf"

    stream_content = b"BT /F1 12 Tf (Whirlpool WDT730PAHZ Dishwasher Spec Sheet) Tj ET"
    compressed = zlib.compress(stream_content)
    pdf_body = b"%PDF-1.4\nstream\n" + compressed + b"\nendstream\n%%EOF"

    fetcher = MockFetcher(
        {unrelated_pdf_url: pdf_body},
        {unrelated_pdf_url: "application/pdf"},
    )
    service = ProductSourceDiscoveryService(fetcher=fetcher)
    profile = ManufacturerProfile(
        manufacturer_id="whirlpool",
        canonical_name="Whirlpool",
        verified_domains=("learnwhirlpool.com",),
    )
    candidates = service.discover(product, profile, candidate_urls=[unrelated_pdf_url])

    assert len(candidates) == 0


# ── TEST 6: Distributor fallback accepted only as SECONDARY ──────────────────
def test_6_distributor_fallback_accepted_only_as_secondary() -> None:
    product = _make_product(mpn="PDSH4816AF", mfg="Frigidaire", brand="Frigidaire")
    dist_url = "https://www.jamindustrialsupply.com/PDSH4816AF"
    dist_html = b"""
    <html>
      <head><title>Frigidaire PDSH4816AF at Jam Industrial</title></head>
      <body>
        <h1>Frigidaire PDSH4816AF Dishwasher</h1>
        <p>Part Number: PDSH4816AF</p>
      </body>
    </html>
    """
    fetcher = MockFetcher({dist_url: dist_html})
    service = ProductSourceDiscoveryService(fetcher=fetcher)
    profile = ManufacturerProfile(
        manufacturer_id="frigidaire",
        canonical_name="Frigidaire",
        verified_domains=("frigidaire.com",),
    )
    candidates = service.discover(product, profile)

    assert len(candidates) > 0
    best = candidates[0]
    assert "jamindustrialsupply.com" in best.url
    assert best.source_kind == SourceKind.DISTRIBUTOR_PRODUCT_PAGE
    assert best.domain_score == 0.75


# ── TEST 7: Distributor does not override manufacturer source ────────────────
def test_7_distributor_does_not_override_manufacturer() -> None:
    mfg_cand = ProductSourceCandidate(
        url="https://www.frigidaire.com/en/p/owner-center/product-support/PDSH4816AF",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        discovery_method="support_page",
        evidence_snippet="PDSH4816AF",
        matched_mpn=True,
        matched_manufacturer=True,
        matched_brand=True,
        identity_score=0.85,
        domain_score=1.0,
        relevance_score=0.85,
    )
    dist_cand = ProductSourceCandidate(
        url="https://www.jamindustrialsupply.com/PDSH4816AF",
        source_kind=SourceKind.DISTRIBUTOR_PRODUCT_PAGE,
        discovery_method="distributor_fallback",
        evidence_snippet="PDSH4816AF",
        matched_mpn=True,
        matched_manufacturer=True,
        matched_brand=True,
        identity_score=0.95,
        domain_score=0.75,
        relevance_score=0.95,
    )

    ranked = sorted([dist_cand, mfg_cand], key=_candidate_rank)
    assert ranked[0].url == (
        "https://www.frigidaire.com/en/p/owner-center/product-support/PDSH4816AF"
    )
    assert ranked[0].source_kind == SourceKind.MANUFACTURER_PRODUCT_PAGE


# ── TEST 8: Gemini search distributor candidate remains secondary ────────────
def test_8_gemini_search_distributor_candidate_remains_secondary() -> None:
    profile = ManufacturerProfile(
        manufacturer_id="frigidaire",
        canonical_name="Frigidaire",
        verified_domains=("frigidaire.com",),
    )
    verifier = SourceVerifier(SourcePolicy())

    gemini_discovered_distributor = SourceRecord(
        canonical_url="https://www.jamindustrialsupply.com/pdsh4816af",
        original_url="https://www.jamindustrialsupply.com/pdsh4816af",
        source_kind=SourceKind.DISTRIBUTOR_PRODUCT_PAGE,
        decision=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
        manufacturer_id="frigidaire",
        manufacturer_domain="jamindustrialsupply.com",
    )

    mfg_res = verifier.verify_source(gemini_discovered_distributor, profile)
    assert mfg_res.decision == SourceDecision.REJECTED

    sec_res = verifier.verify_secondary_source(gemini_discovered_distributor, profile)
    assert sec_res.decision == SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE
    assert sec_res.source_kind == SourceKind.DISTRIBUTOR_PRODUCT_PAGE


# ── TEST 9: PDSH prefix resolves to Frigidaire ───────────────────────────────
def test_9_pdsh_prefix_domain_resolution() -> None:
    resolver = BrandManufacturerResolver()
    resolved = resolver.resolve(
        "Appliance Dealers Cooperative (APPDE)",
        "24 Built-In Dishwasher",
        mpn="PDSH4816AF",
    )
    assert resolved.manufacturer == "frigidaire"
    assert resolved.brand == "Frigidaire"

    domain_resolver = DomainResolver()
    domains = domain_resolver.resolve(
        manufacturer_id=resolved.manufacturer,
        manufacturer_name=resolved.manufacturer,
        brand=resolved.brand,
    )
    verified = [
        d.domain for d in domains if d.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
    ]
    assert "frigidaire.com" in verified


# ── TEST 10: WDTS prefix resolves to Whirlpool ───────────────────────────────
def test_10_wdts_prefix_domain_resolution() -> None:
    resolver = BrandManufacturerResolver()
    resolved = resolver.resolve(
        "Appliance Dealers Cooperative (APPDE)",
        "24 Built-In Dishwasher Stainless",
        mpn="WDTS7024RZ",
    )
    assert resolved.manufacturer == "whirlpool"
    assert resolved.brand == "Whirlpool"

    domain_resolver = DomainResolver()
    domains = domain_resolver.resolve(
        manufacturer_id=resolved.manufacturer,
        manufacturer_name=resolved.manufacturer,
        brand=resolved.brand,
    )
    verified = [
        d.domain for d in domains if d.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
    ]
    assert "whirlpool.com" in verified or "learnwhirlpool.com" in verified


def test_manufacturer_specific_direct_route_precedes_generic_bound() -> None:
    """A bounded direct probe must test the official Frigidaire route first."""
    product = _make_product(mpn="PDSH4816AF", mfg="Frigidaire", brand="Frigidaire")
    official_url = "https://www.frigidaire.com/en/p/owner-center/product-support/PDSH4816AF"
    html = b"""
    <html>
      <head><title>Frigidaire PDSH4816AF Product Support</title></head>
      <body><h1>Model Number: PDSH4816AF</h1></body>
    </html>
    """
    fetcher = MockFetcher({official_url: html})
    service = ProductSourceDiscoveryService(
        fetcher=fetcher,
        max_direct_candidates_per_domain=1,
        max_hypotheses=1,
        max_search_templates_per_domain=0,
        max_sitemap_paths_per_domain=0,
    )
    profile = ManufacturerProfile(
        manufacturer_id="frigidaire",
        canonical_name="Frigidaire",
        verified_domains=("frigidaire.com",),
    )

    candidates = service.discover(product, profile)

    assert candidates
    assert candidates[0].url == official_url
