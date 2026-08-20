"""Comprehensive unit and integration tests covering all 17 gap-closure benchmark scenarios."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from unilog_product_intelligence.application.evaluation import DeterministicEvaluationProvider
from unilog_product_intelligence.domain.truth import (
    AssetType,
    ProductDescriptions,
    ProductTruth,
    RawInputField,
)
from unilog_product_intelligence.enrichment.descriptions import (
    DescriptionContext,
    DescriptionValidator,
    DeterministicDescriptionBuilder,
    is_placeholder_brand,
    is_placeholder_brand_in_text,
)
from unilog_product_intelligence.enrichment.models import (
    PublicationState,
    ReferenceAvailability,
    ValidationSeverity,
)
from unilog_product_intelligence.enrichment.reference import ReferencePack
from unilog_product_intelligence.enrichment.service import EnrichmentService
from unilog_product_intelligence.providers.base import LLMRequest
from unilog_product_intelligence.retrieval.core import (
    ManufacturerProfile,
    RetrievalStatus,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourceRecord,
)
from unilog_product_intelligence.retrieval.digital_assets import (
    DigitalAssetDiscoveryService,
)
from unilog_product_intelligence.retrieval.html_extractor import (
    HtmlProductEvidenceExtractor,
)
from unilog_product_intelligence.retrieval.service import (
    ManufacturerJob,
)
from unilog_product_intelligence.retrieval.source_discovery import (
    AuthorizedDistributorFallbackStrategy,
    MirkaRetrievalStrategy,
    ProductSourceDiscoveryService,
)


# ── Scenario 1: HTML Evidence Extractor parses JSON-LD Product ────────────────
def test_html_evidence_extractor_parses_jsonld_product() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org/",
          "@type": "Product",
          "name": "Diablo 5 in. Thin Kerf Cut-Off Disc",
          "description": "Premium industrial abrasive cut-off disc.",
          "mpn": "DCB518ASTS06G",
          "sku": "DCB518ASTS06G",
          "brand": {"@type": "Brand", "name": "Diablo"},
          "image": "https://diablotools.com/images/products/DCB518ASTS06G.jpg",
          "additionalProperty": [
            {"name": "Diameter", "value": "5 in"},
            {"name": "Thickness", "value": ".045 in"},
            {"name": "Arbor Size", "value": "7/8 in"},
            {"name": "Maximum RPM", "value": "12200 RPM"}
          ]
        }
        </script>
      </head>
      <body><h1>Diablo Cut-Off Disc</h1></body>
    </html>
    """
    extractor = HtmlProductEvidenceExtractor()
    data = extractor.extract(html, "https://diablotools.com/products/DCB518ASTS06G", "src-1")

    assert data.title == "Diablo 5 in. Thin Kerf Cut-Off Disc"
    assert data.brand == "Diablo"
    assert data.mpn == "DCB518ASTS06G"
    assert data.primary_image_url == "https://diablotools.com/images/products/DCB518ASTS06G.jpg"
    assert len(data.specifications) == 4

    spec_dict = {
        s.attribute: (s.normalized_value or s.raw_value, s.unit) for s in data.specifications
    }
    assert spec_dict["Diameter"] == ("5", "in")
    assert spec_dict["Thickness"] == (".045", "in")
    assert spec_dict["Arbor Size"] == ("7/8", "in")


# ── Scenario 2: HTML Evidence Extractor parses HTML Tables ────────────────────
def test_html_evidence_extractor_parses_html_tables() -> None:
    html = """
    <html>
      <body>
        <table class="specs-table">
          <tr><th>Wheel Diameter</th><td>4-1/2 in</td></tr>
          <tr><th>Thickness</th><td>0.040 in</td></tr>
          <tr><th>Arbor</th><td>7/8 in</td></tr>
          <tr><th>Grit</th><td>P60</td></tr>
          <tr><th>Package Quantity</th><td>25</td></tr>
        </table>
      </body>
    </html>
    """
    extractor = HtmlProductEvidenceExtractor()
    data = extractor.extract(html, "https://example.com/item/123", "src-2")

    specs = {s.attribute: (s.normalized_value or s.raw_value, s.unit) for s in data.specifications}
    assert "Diameter" in specs
    assert specs["Diameter"] == ("4-1/2", "in")
    assert "Thickness" in specs
    assert specs["Thickness"] == ("0.040", "in")
    assert "Arbor Size" in specs
    assert specs["Arbor Size"] == ("7/8", "in")
    assert "Package Quantity" in specs
    assert specs["Package Quantity"][0] == "25"


# ── Scenario 3: HTML Evidence Extractor parses Definition Lists ───────────────
def test_html_evidence_extractor_parses_dl_lists() -> None:
    html = """
    <html>
      <body>
        <dl class="product-attributes">
          <dt>Abrasive Material</dt>
          <dd>Ceramic Aluminum Oxide</dd>
          <dt>Max Speed</dt>
          <dd>13300 RPM</dd>
        </dl>
      </body>
    </html>
    """
    extractor = HtmlProductEvidenceExtractor()
    data = extractor.extract(html, "https://example.com/item/456", "src-3")

    specs = {s.attribute: (s.normalized_value or s.raw_value, s.unit) for s in data.specifications}
    assert "Material" in specs
    assert specs["Material"][0] == "Ceramic Aluminum Oxide"
    assert "Maximum RPM" in specs
    assert specs["Maximum RPM"] == ("13300", "RPM")


# ── Scenario 4: UOM Separation on Fractions and Decimals ──────────────────────
def test_html_evidence_extractor_uom_separation() -> None:
    extractor = HtmlProductEvidenceExtractor()
    candidates = extractor.extract_evidence_candidates(
        """
        <table>
          <tr><td>Disc Diameter</td><td>5 in</td></tr>
          <tr><td>Wheel Thickness</td><td>1/16 in</td></tr>
          <tr><td>Arbor Size</td><td>7/8 in</td></tr>
          <tr><td>Max RPM</td><td>12200 RPM</td></tr>
        </table>
        """,
        "https://example.com/test",
        "src-4",
    )
    cands_by_attr = {c.attribute: (c.normalized_candidate, c.unit) for c in candidates}
    assert cands_by_attr["Diameter"] == ("5", "in")
    assert cands_by_attr["Thickness"] == ("1/16", "in")
    assert cands_by_attr["Arbor Size"] == ("7/8", "in")
    assert cands_by_attr["Maximum RPM"] == ("12200", "RPM")


# ── Scenario 5: Deterministic Evaluation Provider Evidence-Grounded Enrichment ─
def test_deterministic_evaluation_provider_evidence_grounded_enrichment() -> None:
    provider = DeterministicEvaluationProvider()
    prompt = """
PLANNED ATTRIBUTES:
- attribute-diameter (Diameter) applicability=REQUIRED allowed_values=[] allowed_uom=['in']
- attribute-thickness (Thickness) applicability=REQUIRED allowed_values=[] allowed_uom=['in']
- attribute-arbor-size (Arbor Size) applicability=REQUIRED allowed_values=[] allowed_uom=['in']
- attribute-material (Material) applicability=RECOMMENDED allowed_values=['AlOx'] allowed_uom=[]

VERIFIED EVIDENCE:
- evidence_id=ev-001 source_id=src-1 text=Diameter: 5 in
- evidence_id=ev-002 source_id=src-1 text=Thickness: .045 in
- evidence_id=ev-003 source_id=src-1 text=Arbor Size: 7/8 in
- evidence_id=ev-004 source_id=src-1 text=Material: AlOx
"""
    req = LLMRequest(
        input_text=prompt,
        task="evidence_grounded_enrichment",
    )
    resp = provider.generate(req)
    data = json.loads(resp.output_text)

    assert "candidates" in data
    assert len(data["candidates"]) == 4

    cand_map = {c["attribute"]: c for c in data["candidates"]}
    assert cand_map["attribute-diameter"]["value"] == "5"
    assert cand_map["attribute-diameter"]["uom"] == "in"
    assert cand_map["attribute-diameter"]["evidence_id"] == "ev-001"

    assert cand_map["attribute-thickness"]["value"] == ".045"
    assert cand_map["attribute-thickness"]["uom"] == "in"
    assert cand_map["attribute-thickness"]["evidence_id"] == "ev-002"

    assert cand_map["attribute-arbor-size"]["value"] == "7/8"
    assert cand_map["attribute-arbor-size"]["uom"] == "in"


# ── Scenario 6: Digital Asset Runtime Integration ─────────────────────────────
def test_asset_discovery_runtime_integration() -> None:
    html = """
    <html>
      <head>
        <meta property="og:image" content="https://diablotools.com/images/og_main.jpg" />
      </head>
      <body>
        <img src="/images/product_zoom.jpg" alt="Diablo Cut-off Disc" />
        <a href="/manuals/spec_sheet.pdf">Technical Specification Sheet</a>
      </body>
    </html>
    """
    service = DigitalAssetDiscoveryService()
    product = ProductTruth(
        product_id="prod-test-1",
        raw_inputs=(
            RawInputField(
                field_name="Mfg_Part_Num",
                raw_value="DCB518ASTS06G",
                source_id="src-1",
            ),
        ),
    )
    assets = service.discover_from_html(
        product=product,
        html_text=html,
        base_url="https://diablotools.com/products/DCB518ASTS06G",
        source_id="src-test-1",
        verified_domains=("diablotools.com",),
        manufacturer_key="diablo",
    )
    assert len(assets) >= 2
    img_types = {AssetType.PRIMARY_IMAGE, AssetType.ALTERNATE_IMAGE}
    img_assets = [a for a in assets if a.asset_type in img_types]
    doc_assets = [a for a in assets if a.asset_type not in img_types]

    assert len(img_assets) >= 1
    expected_imgs = {
        "https://diablotools.com/images/og_main.jpg",
        "https://diablotools.com/images/product_zoom.jpg",
    }
    assert img_assets[0].uri in expected_imgs
    assert len(doc_assets) >= 1
    assert doc_assets[0].uri == "https://diablotools.com/manuals/spec_sheet.pdf"


# ── Scenario 7: Asset Discovery Observability on ManufacturerJob ──────────────
def test_asset_discovery_observability_on_job() -> None:
    job = ManufacturerJob(
        product_id="prod-123",
        asset_discovery_status="success",
        assets_discovered_count=3,
        asset_discovery_error=None,
    )
    assert job.asset_discovery_status == "success"
    assert job.assets_discovered_count == 3
    assert job.asset_discovery_error is None


# ── Scenario 8: Asset Discovery Image Filter Rejects Junk ─────────────────────
def test_asset_discovery_image_filter_rejects_junk() -> None:
    html = """
    <html>
      <body>
        <img src="https://example.com/logo.png" alt="Company Logo" />
        <img src="https://example.com/cart_icon.png" alt="Cart" />
        <img src="https://example.com/social_facebook.jpg" alt="Facebook" />
        <img src="https://example.com/products/main_wheel.jpg" alt="Cutting Wheel 5 in" />
      </body>
    </html>
    """
    service = DigitalAssetDiscoveryService()
    product = ProductTruth(product_id="prod-junk-test")
    assets = service.discover_from_html(
        product=product,
        html_text=html,
        base_url="https://example.com/product/123",
        source_id="src-junk",
        verified_domains=("example.com",),
    )
    uris = [a.uri for a in assets]
    assert "https://example.com/products/main_wheel.jpg" in uris
    assert not any("logo" in u or "cart" in u or "facebook" in u for u in uris)


# ── Scenario 9: Description Placeholder Brand Sanitization ────────────────────
def test_description_placeholder_brand_sanitization() -> None:
    assert is_placeholder_brand("-- No Unilog Brand --") is True
    assert is_placeholder_brand("-- Unbranded --") is True
    assert is_placeholder_brand("-- No DIB Brand --") is True
    assert is_placeholder_brand("-- Unassigned --") is True
    assert is_placeholder_brand("N/A") is True
    assert is_placeholder_brand("Diablo") is False
    assert is_placeholder_brand("Milwaukee") is False

    assert is_placeholder_brand_in_text("The -- No Unilog Brand -- Disc is great") is True
    assert is_placeholder_brand_in_text("Diablo 5 in Cut-off Disc") is False


# ── Scenario 10: Description Brand Priority & Fallback ────────────────────────
def test_description_brand_priority_fallback() -> None:
    product = ProductTruth(
        product_id="prod-brand-test",
        raw_inputs=(
            RawInputField(field_name="Mfg_Part_Num", raw_value="DCB518ASTS06G", source_id="src-1"),
            RawInputField(field_name="Part_Manuf", raw_value="Freud Inc (2435)", source_id="src-1"),
            RawInputField(
                field_name="Unilog_Brand",
                raw_value="-- No Unilog Brand --",
                source_id="src-1",
            ),
            RawInputField(
                field_name="Part_Desc", raw_value="5 in Thin Kerf Disc", source_id="src-1"
            ),
        ),
    )
    ctx = DescriptionContext.from_product(product)
    # Placeholder brand falls back to demasked manufacturer name
    assert ctx.brand == "Freud Inc"
    assert ctx.brand != "-- No Unilog Brand --"


# ── Scenario 11: Description Product Name Priority ────────────────────────────
def test_description_product_name_priority() -> None:
    product = ProductTruth(
        product_id="prod-name-test",
        raw_inputs=(
            RawInputField(field_name="Mfg_Part_Num", raw_value="49-94-0013", source_id="src-1"),
            RawInputField(
                field_name="Part_Desc",
                raw_value="49-94-0013 3IN METAL CUT OFF DISC 5PK",
                source_id="src-1",
            ),
        ),
    )
    # When no verified product title attribute exists, clean MPN repeat prefix
    ctx = DescriptionContext.from_product(product)
    prod_name = ctx.product_name or ""
    assert not prod_name.startswith("49-94-0013")
    assert "METAL CUT OFF DISC" in prod_name


# ── Scenario 12: Description No Unsupported Boilerplate ───────────────────────
def test_description_no_boilerplate() -> None:
    ctx = DescriptionContext(
        product_id="prod-bp-test",
        brand="Diablo",
        manufacturer="Freud Inc",
        mpn="DCB518ASTS06G",
        product_name="5 in Thin Kerf Cut-Off Disc",
        series=None,
        trade_name=None,
        classpath=("Abrasives", "Cut-off Wheels"),
        category="Cut-off Wheels",
        verified_attributes=(),
        evidence_snippets=(),
        approved_uoms=frozenset(),
    )
    builder = DeterministicDescriptionBuilder()
    long_desc = builder.build_long_desc1(ctx)
    retail_desc = builder.build_retail_desc(ctx)

    assert "is an industrial solution" not in long_desc
    assert "delivers reliable performance for professional" not in retail_desc
    assert "Diablo" in long_desc
    assert "DCB518ASTS06G" in long_desc


# ── Scenario 13: Description Validator Blocks Leaked Placeholder ──────────────
def test_description_validator_blocks_leaked_placeholder() -> None:
    validator = DescriptionValidator()
    ctx = DescriptionContext(
        product_id="prod-val-test",
        brand=None,
        manufacturer="Test Mfg",
        mpn="MPN123",
        product_name="Test Product",
        series=None,
        trade_name=None,
        classpath=(),
        category="Tools",
        verified_attributes=(),
        evidence_snippets=(),
        approved_uoms=frozenset(),
    )
    descs = ProductDescriptions(
        short="MPN123 -- No Unilog Brand -- Product",
        long="-- No Unilog Brand -- MPN123 full overview.",
        mobile="MPN123 Product",
        invoice="MPN123 PRODUCT",
        retail="MPN123 Product in Tools.",
    )
    results = validator.validate(descs, ctx)
    blocking_errors = [
        r for r in results if not r.passed and r.severity == ValidationSeverity.BLOCKING
    ]
    assert len(blocking_errors) >= 1
    assert any("placeholder_leakage" in r.validator for r in blocking_errors)


# ── Scenario 14: Enrichment Service Blocks Publication on Description Errors ───
def test_enrichment_service_blocks_publication_on_description_errors() -> None:
    planner = MagicMock()
    planner.reference_pack = ReferencePack(availability=ReferenceAvailability.REFERENCE_UNAVAILABLE)
    desc_failure = MagicMock(passed=False, severity=ValidationSeverity.BLOCKING)
    mock_desc_svc = MagicMock()
    mock_desc_svc.generate_descriptions.return_value = (None, [desc_failure])

    service = EnrichmentService(planner=planner, description_service=mock_desc_svc)
    product = ProductTruth(
        product_id="prod-svc-test",
        raw_inputs=(
            RawInputField(field_name="Mfg_Part_Num", raw_value="DCB518ASTS06G", source_id="src-1"),
            RawInputField(
                field_name="Unilog_Brand",
                raw_value="-- No Unilog Brand --",
                source_id="src-1",
            ),
        ),
    )
    mock_desc_svc.generate_descriptions.return_value = (product, [desc_failure])
    result = service.enrich(product)
    assert result.publication_state == PublicationState.BLOCKED


# ── Scenario 15: Mirka Retrieval Strategy ─────────────────────────────────────
def test_mirka_retrieval_strategy() -> None:
    strategy = MirkaRetrievalStrategy()
    profile = ManufacturerProfile(
        manufacturer_id="mirka",
        canonical_name="Mirka Abrasives",
        verified_domains=("www.mirka.com", "mirka.com"),
    )
    assert strategy.matches(profile, ("www.mirka.com",)) is True

    product = ProductTruth(
        product_id="prod-mirka-1",
        raw_inputs=(
            RawInputField(field_name="Mfg_Part_Num", raw_value="5B-332-080", source_id="src-1"),
            RawInputField(
                field_name="Part_Desc",
                raw_value="5B-332-080 HIOLIT Sanding Disc 80 Grit",
                source_id="src-1",
            ),
        ),
    )
    from unilog_product_intelligence.retrieval.mpn_normalizer import (
        MpnHypothesis,
        MpnHypothesisType,
    )

    hypotheses = [
        MpnHypothesis(
            value="5B-332-080",
            hypothesis_type=MpnHypothesisType.RAW,
            confidence=1.0,
            is_lossless=True,
            identity_eligible=True,
        ),
        MpnHypothesis(
            value="5B332080",
            hypothesis_type=MpnHypothesisType.LOSSLESS_NORMALIZED,
            confidence=0.95,
            is_lossless=True,
            identity_eligible=True,
        ),
    ]
    search_urls = strategy.search_urls("www.mirka.com", hypotheses, product, profile)
    assert any("searchTerm=5B-332-080" in u for u in search_urls)
    assert any("searchTerm=HIOLIT" in u for u in search_urls)


# ── Scenario 16: Authorized Distributor Secondary Fallback ───────────────────
def test_authorized_distributor_fallback_strategy() -> None:
    strategy = AuthorizedDistributorFallbackStrategy()
    product = ProductTruth(
        product_id="prod-3m-1",
        raw_inputs=(
            RawInputField(field_name="Mfg_Part_Num", raw_value="7100075678", source_id="src-1"),
            RawInputField(field_name="Part_Manuf", raw_value="3M", source_id="src-1"),
        ),
    )
    from unilog_product_intelligence.retrieval.mpn_normalizer import (
        MpnHypothesis,
        MpnHypothesisType,
    )

    hypotheses = [
        MpnHypothesis(
            value="7100075678",
            hypothesis_type=MpnHypothesisType.RAW,
            confidence=1.0,
            is_lossless=True,
            identity_eligible=True,
        )
    ]
    urls = strategy.generate_urls(product, hypotheses)
    assert len(urls) >= 3
    assert any("3m-7100075678" in u for u in urls)
    assert any("grainger.com" in u for u in urls)
    assert any("zoro.com" in u for u in urls)


# ── Scenario 17: WAF Circuit Breaker ──────────────────────────────────────────
def test_waf_circuit_breaker() -> None:
    # Mock fetcher to return HTTP 403 on first call to 3m.com
    fetcher = MagicMock(spec=SourceFetcher)
    blocked_source = SourceRecord(
        canonical_url="https://www.3m.com/products/7100075678",
        original_url="https://www.3m.com/products/7100075678",
        source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
        decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
        manufacturer_id="3m",
        manufacturer_domain="www.3m.com",
        retrieval_status=RetrievalStatus.BLOCKED,
        http_status=403,
    )
    fetcher.fetch.return_value = MagicMock(source=blocked_source, body=b"")

    discovery = ProductSourceDiscoveryService(fetcher=fetcher)
    profile = ManufacturerProfile(
        manufacturer_id="3m",
        canonical_name="3M",
        verified_domains=("www.3m.com",),
    )
    product = ProductTruth(
        product_id="prod-waf-test",
        raw_inputs=(
            RawInputField(field_name="Mfg_Part_Num", raw_value="7100075678", source_id="src-1"),
            RawInputField(field_name="Part_Manuf", raw_value="3M", source_id="src-1"),
        ),
    )
    discovery.discover(product, profile)
    # The discovery service should trip the circuit breaker on 3m.com and record waf_blocked
    assert discovery.domain_attempt_failure_reasons.get("www.3m.com") == "waf_blocked"
    # Because 3m.com was WAF blocked, it did not execute 20 subsequent 3m.com URLs in a loop
    assert fetcher.fetch.call_count <= 15
