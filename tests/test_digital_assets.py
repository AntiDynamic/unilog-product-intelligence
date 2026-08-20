"""Tests for Authoritative Digital Asset and Document Discovery (Phase 7)."""

from __future__ import annotations

from pathlib import Path

from unilog_product_intelligence.agents.orchestration import JobState, ProductJob
from unilog_product_intelligence.application.phase65 import Phase65Result, Phase65Status
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.delivery.adapter import (
    DeliverySchemaContract,
    Phase65ResultDeliveryAdapter,
)
from unilog_product_intelligence.domain.models import Source, SourceAuthority, SourceType
from unilog_product_intelligence.domain.truth import (
    AssetType,
    DigitalAsset,
    ProductClassification,
    ProductTruth,
)
from unilog_product_intelligence.retrieval.digital_assets import (
    AssetAssociationScope,
    AssetAuthorityVerifier,
    AssetBudgetConfig,
    AssetContentStatus,
    DigitalAssetDiscoveryService,
    DocumentClassifier,
)


def _make_test_product(mpn: str = "49-94-0013", brand: str = "Milwaukee Tool") -> ProductTruth:
    source = Source(
        source_id="src-mfg-1",
        source_type=SourceType.MANUFACTURER_DOCUMENT,
        authority=SourceAuthority.AUTHORITATIVE,
        uri="https://www.milwaukeetool.com/Products/49-94-0013",
    )
    truth = ProductTruthService().create_from_raw_input(
        "prod-100",
        {
            "Mfg_Part_Num": mpn,
            "Part_Desc": "Cut-Off Wheel",
            "Unilog_Brand": brand,
            "Part_Manuf": brand,
        },
        source,
    )
    return ProductTruthService().add_classification(
        truth,
        ProductClassification(
            class_name="Cut-Off Wheels",
            classpath=("Abrasives", "Cut-Off Wheels"),
        ),
    )


# ==============================================================================
# TEST A — PRODUCT IMAGE DISCOVERY
# ==============================================================================


def test_product_image_discovery_filters_logos() -> None:
    """Discovers main & alternate images and filters out logos and sprites."""
    product = _make_test_product()
    html = """
    <html>
      <body>
        <img src="/images/nav_header_logo.png" alt="Company Logo" />
        <div class="gallery">
          <img src="/media/49-94-0013_main_large.jpg" alt="49-94-0013 Cut-Off Wheel Main" />
          <img src="/media/49-94-0013_angle_view.jpg" alt="49-94-0013 Angle View" />
          <img src="/images/social_facebook_icon.png" alt="Facebook" />
        </div>
      </body>
    </html>
    """
    service = DigitalAssetDiscoveryService()
    assets = service.discover_from_html(
        product=product,
        html_text=html,
        base_url="https://www.milwaukeetool.com/Products/49-94-0013",
        source_id="src-mfg-1",
        verified_domains=("milwaukeetool.com",),
        manufacturer_key="Milwaukee Tool",
    )

    img_types = {AssetType.PRIMARY_IMAGE, AssetType.ALTERNATE_IMAGE}
    images = [a for a in assets if a.asset_type in img_types]
    assert len(images) == 2

    # Primary image is main
    primary = images[0]
    assert primary.asset_type == AssetType.PRIMARY_IMAGE
    assert "49-94-0013_main_large.jpg" in primary.uri

    # Alternate image
    alt = images[1]
    assert alt.asset_type == AssetType.ALTERNATE_IMAGE
    assert "49-94-0013_angle_view.jpg" in alt.uri

    # Logos and social icons were filtered out
    assert not any("logo" in a.uri.lower() for a in assets)
    assert not any("facebook" in a.uri.lower() for a in assets)


# ==============================================================================
# TEST B — DOCUMENT DISCOVERY & CLASSIFICATION
# ==============================================================================


def test_document_discovery_and_classification() -> None:
    """Discovers and classifies documents into specific AssetTypes."""
    product = _make_test_product()
    html = """
    <html>
      <body>
        <div class="resources">
          <a href="/docs/49-94-0013_specification_sheet.pdf">Technical Specification</a>
          <a href="/docs/cut_off_wheel_installation_instructions.pdf">Installation Guide</a>
          <a href="/docs/milwaukee_tool_warranty.pdf">Warranty Document</a>
          <a href="/docs/abrasives_sds_safety_data.pdf">Safety Data Sheet</a>
          <a href="/cad/49-94-0013_dimensional_drawing.dwg">CAD Line Drawing</a>
          <a href="/docs/2026_abrasives_full_line_catalog.pdf">Full Catalog</a>
        </div>
      </body>
    </html>
    """
    service = DigitalAssetDiscoveryService()
    assets = service.discover_from_html(
        product=product,
        html_text=html,
        base_url="https://www.milwaukeetool.com/Products/49-94-0013",
        source_id="src-mfg-1",
        verified_domains=("milwaukeetool.com",),
        manufacturer_key="Milwaukee Tool",
    )

    img_types = {AssetType.PRIMARY_IMAGE, AssetType.ALTERNATE_IMAGE}
    docs = [a for a in assets if a.asset_type not in img_types]
    assert len(docs) == 6

    types = {a.asset_type for a in docs}
    assert AssetType.SPECIFICATION_SHEET in types
    assert AssetType.INSTALLATION_MANUAL in types
    assert AssetType.WARRANTY in types
    assert AssetType.SDS in types
    assert AssetType.CAD_DRAWING in types
    assert AssetType.CATALOG in types


# ==============================================================================
# TEST C — THIRD-PARTY DOMAIN REJECTION
# ==============================================================================


def test_third_party_domain_rejection() -> None:
    """Rejects third-party marketplace asset links."""
    product = _make_test_product()
    html = """
    <html>
      <body>
        <img src="https://m.media-amazon.com/images/I/49-94-0013.jpg" alt="Amazon Image" />
        <a href="https://www.grainger.com/ec/pdf/spec.pdf">Grainger Spec</a>
        <img src="https://www.milwaukeetool.com/media/wheel.jpg" alt="Official Image" />
      </body>
    </html>
    """
    service = DigitalAssetDiscoveryService()
    assets = service.discover_from_html(
        product=product,
        html_text=html,
        base_url="https://www.milwaukeetool.com/Products/49-94-0013",
        source_id="src-mfg-1",
        verified_domains=("milwaukeetool.com",),
        manufacturer_key="Milwaukee Tool",
    )

    assert len(assets) == 1
    assert "milwaukeetool.com" in assets[0].uri
    assert not any("amazon" in a.uri for a in assets)
    assert not any("grainger" in a.uri for a in assets)


# ==============================================================================
# TEST D — VERIFIED MANUFACTURER ASSET HOST
# ==============================================================================


def test_verified_manufacturer_asset_host() -> None:
    """Accepts multimedia.3m.com as authoritative for 3M."""
    product = _make_test_product(mpn="3MABR-7", brand="3M")
    html = """
    <html>
      <body>
        <img src="https://multimedia.3m.com/mws/media/12345/3m-disc.jpg" alt="3M Disc" />
        <a href="https://multimedia.3m.com/mws/media/67890/sds.pdf">Safety Data Sheet</a>
      </body>
    </html>
    """
    service = DigitalAssetDiscoveryService()
    assets = service.discover_from_html(
        product=product,
        html_text=html,
        base_url="https://www.3m.com/products/abrasives",
        source_id="src-3m-1",
        verified_domains=("3m.com",),
        manufacturer_key="3M",
    )

    assert len(assets) == 2
    assert all("multimedia.3m.com" in a.uri for a in assets)


# ==============================================================================
# TEST E — PRODUCT ASSOCIATION SCOPE
# ==============================================================================


def test_product_association_scope() -> None:
    """Marks document with MPN as PRODUCT_SPECIFIC."""
    classifier = DocumentClassifier()
    scope = classifier.determine_association(
        url="https://www.milwaukeetool.com/docs/49-94-0013-datasheet.pdf",
        target_mpn="49-94-0013",
        title="49-94-0013 Cut-Off Wheel Spec",
    )
    assert scope == AssetAssociationScope.PRODUCT_SPECIFIC


# ==============================================================================
# TEST F — WRONG PRODUCT DOCUMENT
# ==============================================================================


def test_wrong_product_document_marked_general_or_wrong() -> None:
    """Document without target MPN is not tagged as exact match when explicit catalog."""
    classifier = DocumentClassifier()
    scope = classifier.determine_association(
        url="https://www.milwaukeetool.com/docs/full-line-catalog-2026.pdf",
        target_mpn="49-94-0013",
        title="General Line Catalog",
        is_catalog=True,
    )
    assert scope == AssetAssociationScope.MANUFACTURER_GENERAL


# ==============================================================================
# TEST G — GENERAL CATALOG
# ==============================================================================


def test_general_catalog_classification() -> None:
    """Classifies catalog as CATALOG with MANUFACTURER_GENERAL scope."""
    classifier = DocumentClassifier()
    doc_type = classifier.classify_type(
        url="https://www.diablotools.com/resources/diablo_full_catalog.pdf",
        title="Diablo Full Product Catalog",
    )
    scope = classifier.determine_association(
        url="https://www.diablotools.com/resources/diablo_full_catalog.pdf",
        target_mpn="DCB518ASTS06G",
        is_catalog=True,
    )
    assert doc_type == AssetType.CATALOG
    assert scope == AssetAssociationScope.MANUFACTURER_GENERAL


# ==============================================================================
# TEST H — DUPLICATE URL DEDUPLICATION
# ==============================================================================


def test_duplicate_url_deduplication() -> None:
    """Duplicate URLs on the same page produce only one DigitalAsset record."""
    product = _make_test_product()
    html = """
    <html>
      <body>
        <img src="/media/wheel.jpg" alt="Image 1" />
        <a href="/media/wheel.jpg">High Res Image</a>
        <a href="/docs/spec.pdf">Spec Sheet Top</a>
        <a href="/docs/spec.pdf?utm_source=page">Spec Sheet Bottom</a>
      </body>
    </html>
    """
    service = DigitalAssetDiscoveryService()
    assets = service.discover_from_html(
        product=product,
        html_text=html,
        base_url="https://www.milwaukeetool.com/Products/49-94-0013",
        source_id="src-mfg-1",
        verified_domains=("milwaukeetool.com",),
        manufacturer_key="Milwaukee Tool",
    )

    uris = [a.uri for a in assets]
    assert len(uris) == len(set(uris))
    assert len(assets) == 2


# ==============================================================================
# TEST I — REDIRECT SECURITY
# ==============================================================================


def test_authority_verifier_same_and_subdomain() -> None:
    """Verifies same domain and subdomains are allowed while external are rejected."""
    verifier = AssetAuthorityVerifier()
    assert verifier.is_authoritative(
        "https://media.milwaukeetool.com/img.jpg",
        verified_domains=("milwaukeetool.com",),
        manufacturer_key="Milwaukee Tool",
    )
    assert not verifier.is_authoritative(
        "https://evil.example.com/img.jpg",
        verified_domains=("milwaukeetool.com",),
        manufacturer_key="Milwaukee Tool",
    )


# ==============================================================================
# TEST J — MAX ASSET BUDGET
# ==============================================================================


def test_asset_budget_bounds_enforced() -> None:
    """Enforces configurable limits on maximum images and documents."""
    product = _make_test_product()
    img_tags = "\n".join(f'<img src="/media/img_{i}.jpg" alt="Img {i}" />' for i in range(30))
    doc_tags = "\n".join(f'<a href="/docs/doc_{i}.pdf">Doc {i}</a>' for i in range(30))
    html = f"<html><body>{img_tags}{doc_tags}</body></html>"

    budget = AssetBudgetConfig(max_images=5, max_documents=8)
    service = DigitalAssetDiscoveryService(budget=budget)
    assets = service.discover_from_html(
        product=product,
        html_text=html,
        base_url="https://www.milwaukeetool.com/Products/49-94-0013",
        source_id="src-mfg-1",
        verified_domains=("milwaukeetool.com",),
        manufacturer_key="Milwaukee Tool",
    )

    img_types = {AssetType.PRIMARY_IMAGE, AssetType.ALTERNATE_IMAGE}
    images = [a for a in assets if a.asset_type in img_types]
    docs = [a for a in assets if a.asset_type not in img_types]

    assert len(images) == 5
    assert len(docs) == 8


# ==============================================================================
# TEST K — DELIVERY ADAPTER INTEGRATION
# ==============================================================================


def test_delivery_adapter_maps_discovered_digital_assets() -> None:
    """Discovered images, SDS, and documents land in observed 252-column delivery fields."""
    product = _make_test_product()
    product.digital_assets = [
        DigitalAsset(
            asset_id="a-1",
            asset_type=AssetType.PRIMARY_IMAGE,
            uri="https://www.milwaukeetool.com/media/49-94-0013_main.jpg",
            source_id="src-1",
        ),
        DigitalAsset(
            asset_id="a-2",
            asset_type=AssetType.ALTERNATE_IMAGE,
            uri="https://www.milwaukeetool.com/media/49-94-0013_alt1.jpg",
            source_id="src-1",
        ),
        DigitalAsset(
            asset_id="a-3",
            asset_type=AssetType.SPECIFICATION_SHEET,
            uri="https://www.milwaukeetool.com/docs/spec_sheet.pdf",
            title="Specification Sheet",
            source_id="src-1",
        ),
        DigitalAsset(
            asset_id="a-4",
            asset_type=AssetType.INSTALLATION_MANUAL,
            uri="https://www.milwaukeetool.com/docs/installation_guide.pdf",
            title="Installation Manual",
            source_id="src-1",
        ),
        DigitalAsset(
            asset_id="a-5",
            asset_type=AssetType.WARRANTY,
            uri="https://www.milwaukeetool.com/docs/warranty.pdf",
            title="Warranty Information",
            source_id="src-1",
        ),
        DigitalAsset(
            asset_id="a-6",
            asset_type=AssetType.SDS,
            uri="https://www.milwaukeetool.com/docs/sds.pdf",
            title="Safety Data Sheet",
            source_id="src-1",
        ),
        DigitalAsset(
            asset_id="a-7",
            asset_type=AssetType.CAD_DRAWING,
            uri="https://www.milwaukeetool.com/cad/line_drawing.dwg",
            title="Line Drawing",
            source_id="src-1",
        ),
    ]

    root = Path(__file__).resolve().parent.parent
    schema_path = root / "docs" / "research" / "delivery-schema.json"
    contract = DeliverySchemaContract.from_json(schema_path)
    adapter = Phase65ResultDeliveryAdapter(contract)

    phase65_res = Phase65Result(
        product_truth=product,
        phase4_job=ProductJob(
            job_id="job-1", product_id=product.product_id, state=JobState.CANDIDATES_ACCEPTED
        ),
        status=Phase65Status.ENRICHED,
        resolved_manufacturer="Milwaukee Tool",
        resolved_brand="Milwaukee Tool",
    )

    record = adapter.to_record(phase65_res)
    values = record.values

    assert values["Product Image"] == "https://www.milwaukeetool.com/media/49-94-0013_main.jpg"
    assert values["Actual Image (Yes/No)"] == "Yes"
    assert values["Alternate Image 1"] == "https://www.milwaukeetool.com/media/49-94-0013_alt1.jpg"
    assert values["Specification Sheet"] == "https://www.milwaukeetool.com/docs/spec_sheet.pdf"
    assert (
        values["Instruction/Installation Manual"]
        == "https://www.milwaukeetool.com/docs/installation_guide.pdf"
    )
    assert values["Warranty Information"] == "https://www.milwaukeetool.com/docs/warranty.pdf"
    assert values["SDS"] == "https://www.milwaukeetool.com/docs/sds.pdf"
    assert values["Line Drawing"] == "https://www.milwaukeetool.com/cad/line_drawing.dwg"


# ==============================================================================
# TEST L — UNPARSEABLE PDF HANDLING
# ==============================================================================


def test_unparseable_pdf_retains_url_without_fabricating_evidence() -> None:
    """Retains URL with content_status = NOT_PARSED and attaches no fabricated candidates."""
    asset = DigitalAsset(
        asset_id="a-pdf-1",
        asset_type=AssetType.SPECIFICATION_SHEET,
        uri="https://www.milwaukeetool.com/docs/spec.pdf",
        source_id="src-1",
        content_status=AssetContentStatus.NOT_PARSED.value,
        evidence_ids=[],
    )

    assert asset.uri == "https://www.milwaukeetool.com/docs/spec.pdf"
    assert asset.content_status == "NOT_PARSED"
    assert not asset.evidence_ids
