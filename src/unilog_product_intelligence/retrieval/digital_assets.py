"""Phase 7: Authoritative Digital Asset and Document Discovery.

Discovers, verifies, classifies, and attaches product images, alternate images,
specification sheets, technical data sheets, installation/user manuals, warranties,
SDS, catalogs, brochures, and CAD/drawings from verified manufacturer product pages.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4

from unilog_product_intelligence.domain.models import SourceStatus
from unilog_product_intelligence.domain.truth import AssetType, DigitalAsset, ProductTruth
from unilog_product_intelligence.retrieval.core import canonicalize_url


class AssetAssociationScope(StrEnum):
    PRODUCT_SPECIFIC = "PRODUCT_SPECIFIC"
    CATEGORY_LEVEL = "CATEGORY_LEVEL"
    MANUFACTURER_GENERAL = "MANUFACTURER_GENERAL"
    WRONG_PRODUCT = "WRONG_PRODUCT"


class AssetContentStatus(StrEnum):
    PARSED = "PARSED"
    NOT_PARSED = "NOT_PARSED"
    PARSE_FAILED = "PARSE_FAILED"


@dataclass(frozen=True)
class AssetBudgetConfig:
    max_images: int = 10
    max_alt_images: int = 4
    max_documents: int = 20
    max_page_bytes: int = 10_000_000


# Known authorized manufacturer-controlled asset hosts
KNOWN_MANUFACTURER_ASSET_HOSTS: dict[str, tuple[str, ...]] = {
    "3m": (
        "multimedia.3m.com",
        "3m.com",
        "www.3m.com",
        "workersafety.3m.com",
        "media.3m.com",
        "content.3m.com",
    ),
    "milwaukee": (
        "milwaukeetool.com",
        "www.milwaukeetool.com",
        "media.milwaukeetool.com",
        "images.milwaukeetool.com",
        "milwaukeetool.scene7.com",
    ),
    "diablo": (
        "diablotools.com",
        "www.diablotools.com",
        "media.diablotools.com",
        "cdn.shopify.com",
        "ik.imagekit.io",
        "imagekit.io",
        "freudtools.com",
        "www.freudtools.com",
    ),
    "freud": (
        "freudtools.com",
        "www.freudtools.com",
        "diablotools.com",
        "www.diablotools.com",
        "cdn.shopify.com",
        "ik.imagekit.io",
        "imagekit.io",
    ),
    "mirka": (
        "mirka.com",
        "www.mirka.com",
        "mirkausa.com",
        "cms.mirka.com",
        "media.mirka.com",
    ),
    "kohler": (
        "kohler.com",
        "www.kohler.com",
        "us.kohler.com",
        "s7d2.scene7.com",
    ),
    "nibco": (
        "nibco.com",
        "www.nibco.com",
    ),
}

DISALLOWED_THIRD_PARTY_DOMAINS: frozenset[str] = frozenset({
    "amazon.com",
    "amazon.co.uk",
    "amazon.ca",
    "grainger.com",
    "ebay.com",
    "walmart.com",
    "homedepot.com",
    "lowes.com",
    "mscdirect.com",
    "zoro.com",
    "aliexpress.com",
    "alibaba.com",
    "target.com",
    "wayfair.com",
})

IMAGE_EXCLUSION_KEYWORDS: frozenset[str] = frozenset({
    "logo",
    "icon",
    "badge",
    "sprite",
    "arrow",
    "cart",
    "search",
    "pixel",
    "social",
    "facebook",
    "twitter",
    "instagram",
    "youtube",
    "linkedin",
    "spinner",
    "loading",
    "1x1",
    "favicon",
    "banner_ad",
    "nav_",
    "header_logo",
    "footer_logo",
    "payment",
    "visa",
    "mastercard",
    "amex",
    "paypal",
})

DOC_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf",
    ".doc",
    ".docx",
    ".dwg",
    ".dxf",
    ".step",
    ".stp",
    ".rtf",
    ".txt",
})


def _clean_url(url: str) -> str:
    """Canonicalize and remove tracking query params."""
    try:
        parts = urlsplit(canonicalize_url(url))
        query_dict = parse_qs(parts.query, keep_blank_values=False)
        # Drop tracking parameters
        clean_query = {
            k: v
            for k, v in query_dict.items()
            if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref", "trk"))
        }
        encoded_query = urlencode(clean_query, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, encoded_query, ""))
    except Exception:
        return url.strip()


def _extract_domain(url: str) -> str:
    try:
        netloc = urlsplit(url).netloc.casefold()
        if ":" in netloc:
            netloc = netloc.split(":", 1)[0]
        return netloc
    except Exception:
        return ""


def _same_or_subdomain(host: str, domain: str) -> bool:
    h = host.casefold().strip()
    d = domain.casefold().strip()
    return h == d or h.endswith("." + d)


# ==============================================================================
# AUTHORITY VERIFIER
# ==============================================================================


class AssetAuthorityVerifier:
    """Verifies that an asset originates from the verified manufacturer or authorized hosts."""

    def is_authoritative(
        self,
        asset_url: str,
        verified_domains: tuple[str, ...],
        manufacturer_key: str | None = None,
    ) -> bool:
        host = _extract_domain(asset_url)
        if not host:
            return False

        # Reject known third-party marketplaces and general retail sites
        for blocked in DISALLOWED_THIRD_PARTY_DOMAINS:
            if _same_or_subdomain(host, blocked):
                return False

        # Check against verified domains (and their subdomains)
        for vdomain in verified_domains:
            if vdomain and (_same_or_subdomain(host, vdomain) or _same_or_subdomain(vdomain, host)):
                return True

        # Check against known authorized manufacturer asset hosts
        if manufacturer_key:
            m_key = manufacturer_key.casefold().strip()
            for key, allowed_hosts in KNOWN_MANUFACTURER_ASSET_HOSTS.items():
                if key in m_key or m_key in key:
                    for allowed in allowed_hosts:
                        if _same_or_subdomain(host, allowed):
                            return True

        return False


# ==============================================================================
# DOCUMENT CLASSIFIER
# ==============================================================================


class DocumentClassifier:
    """Classifies document types and determines product association scope."""

    def classify_type(
        self,
        url: str,
        title: str | None = None,
        anchor_text: str | None = None,
    ) -> AssetType:
        text = f"{url} {title or ''} {anchor_text or ''}".casefold()
        filename = Path(urlsplit(url).path).name.casefold()

        # 1. SDS / MSDS
        if any(tok in text for tok in ["sds", "msds", "safety data sheet", "safety-data-sheet"]):
            return AssetType.SDS

        # 2. Warranty
        if any(tok in text for tok in ["warranty", "guarantee", "limited warranty"]):
            return AssetType.WARRANTY

        # 3. Installation / Instruction Manual
        if any(
            tok in text
            for tok in [
                "install",
                "installation",
                "instruction",
                "setup guide",
                "mounting",
                "assembly",
                "installation manual",
                "installation instructions",
            ]
        ):
            return AssetType.INSTALLATION_MANUAL

        # 4. User / Owner Manual
        if any(
            tok in text
            for tok in [
                "user manual",
                "user guide",
                "owners manual",
                "owner's manual",
                "operator manual",
                "operating instructions",
            ]
        ):
            return AssetType.USER_MANUAL

        # 5. CAD / Drawings
        if (
            any(
                tok in text
                for tok in [
                    "cad",
                    "dwg",
                    "dxf",
                    "step",
                    "stp",
                    "line drawing",
                    "dimensional drawing",
                    "engineering drawing",
                    "blueprint",
                    "diagram",
                    "dimension",
                ]
            )
            or filename.endswith((".dwg", ".dxf", ".step", ".stp"))
        ):
            return AssetType.CAD_DRAWING

        # 6. Catalog / Brochure
        if any(
            tok in text
            for tok in [
                "catalog",
                "catalogue",
                "brochure",
                "flyer",
                "pamphlet",
                "line card",
                "full line",
            ]
        ):
            return AssetType.CATALOG

        # 7. Technical Data Sheet / Specification Sheet
        if any(
            tok in text
            for tok in [
                "spec sheet",
                "specification",
                "tech sheet",
                "technical sheet",
                "datasheet",
                "data sheet",
                "cutsheet",
                "cut sheet",
                "technical data",
                "technical bulletin",
                "submittal",
                "product data",
                "tds",
            ]
        ):
            return AssetType.SPECIFICATION_SHEET

        return AssetType.OTHER_DOCUMENT

    def determine_association(
        self,
        url: str,
        target_mpn: str | None,
        title: str | None = None,
        anchor_text: str | None = None,
        is_catalog: bool = False,
    ) -> AssetAssociationScope:
        if is_catalog:
            return AssetAssociationScope.MANUFACTURER_GENERAL

        if not target_mpn:
            return AssetAssociationScope.PRODUCT_SPECIFIC

        clean_mpn = target_mpn.casefold().replace("-", "").replace(" ", "")
        raw_mpn = target_mpn.casefold().strip()

        combined = f"{url} {title or ''} {anchor_text or ''}".casefold()
        combined_clean = combined.replace("-", "").replace(" ", "").replace("_", "")

        # Check if target MPN is present
        if raw_mpn in combined or clean_mpn in combined_clean:
            return AssetAssociationScope.PRODUCT_SPECIFIC

        # If it's a general warranty or full-line catalog
        if any(tok in combined for tok in ["warranty", "full line", "general catalog", "brochure"]):
            return AssetAssociationScope.MANUFACTURER_GENERAL

        # Default for documents directly linked from verified single-product page
        return AssetAssociationScope.PRODUCT_SPECIFIC


# ==============================================================================
# HTML / ASSET EXTRACTOR
# ==============================================================================


class _AssetHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.images: list[dict[str, str]] = []
        self.documents: list[dict[str, str]] = []
        self.jsonld_scripts: list[str] = []
        self._in_jsonld = False
        self._jsonld_buf: list[str] = []
        self._current_anchor: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.casefold(): v for k, v in attrs if v is not None}

        if tag == "script":
            if attr_dict.get("type", "").casefold() == "application/ld+json":
                self._in_jsonld = True
            return

        if tag == "img":
            # Extract src, data-src, zoom, large, alt, title
            src = (
                attr_dict.get("src")
                or attr_dict.get("data-src")
                or attr_dict.get("data-zoom-image")
                or attr_dict.get("data-large")
                or attr_dict.get("data-highres")
            )
            if src:
                self.images.append({
                    "url": urljoin(self.base_url, src),
                    "alt": attr_dict.get("alt", ""),
                    "title": attr_dict.get("title", ""),
                })

        if tag == "source":
            srcset = attr_dict.get("srcset")
            if srcset:
                first_src = srcset.split(",")[0].strip().split(" ")[0].strip()
                if first_src:
                    self.images.append({
                        "url": urljoin(self.base_url, first_src),
                        "alt": "",
                        "title": "",
                    })

        if tag == "meta":
            prop = attr_dict.get("property", "").casefold() or attr_dict.get("name", "").casefold()
            content = attr_dict.get("content", "")
            if prop in {"og:image", "twitter:image"} and content:
                self.images.append({
                    "url": urljoin(self.base_url, content),
                    "alt": "og:image",
                    "title": "OpenGraph Image",
                })

        if tag == "a":
            href = attr_dict.get("href")
            if href and not href.casefold().startswith(("javascript:", "mailto:", "tel:", "#")):
                full_url = urljoin(self.base_url, href)
                self._current_anchor = {
                    "url": full_url,
                    "title": attr_dict.get("title", ""),
                    "text": "",
                }

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            raw = "".join(self._jsonld_buf).strip()
            if raw:
                self.jsonld_scripts.append(raw)
            self._jsonld_buf = []

        if tag == "a" and self._current_anchor:
            url = self._current_anchor["url"]
            path = urlsplit(url).path.casefold()
            # If link has document extension or resource keyword
            doc_kws = ["/download", "/document", "/spec", "/manual", "/sds"]
            if any(path.endswith(ext) for ext in DOC_EXTENSIONS) or any(
                kw in url.casefold() for kw in doc_kws
            ):
                self.documents.append(self._current_anchor)
            elif any(path.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                self.images.append({
                    "url": url,
                    "alt": self._current_anchor.get("text", ""),
                    "title": self._current_anchor.get("title", ""),
                })
            self._current_anchor = None

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self._current_anchor:
            text = data.strip()
            if text:
                curr = self._current_anchor.get("text", "")
                self._current_anchor["text"] = f"{curr} {text}".strip()


# ==============================================================================
# DIGITAL ASSET DISCOVERY SERVICE
# ==============================================================================


class DigitalAssetDiscoveryService:
    """Discovers, validates authority, classifies, and attaches digital assets to ProductTruth."""

    def __init__(
        self,
        verifier: AssetAuthorityVerifier | None = None,
        classifier: DocumentClassifier | None = None,
        budget: AssetBudgetConfig | None = None,
    ) -> None:
        self.verifier = verifier or AssetAuthorityVerifier()
        self.classifier = classifier or DocumentClassifier()
        self.budget = budget or AssetBudgetConfig()

    def discover_from_html(
        self,
        product: ProductTruth,
        html_text: str,
        base_url: str,
        source_id: str,
        verified_domains: tuple[str, ...],
        manufacturer_key: str | None = None,
    ) -> list[DigitalAsset]:
        parser = _AssetHTMLParser(base_url)
        parser.feed(html_text)

        # Parse JSON-LD structured data for images
        for script_raw in parser.jsonld_scripts:
            try:
                data = json.loads(script_raw)
                self._extract_jsonld_assets(data, base_url, parser.images)
            except Exception:
                continue

        target_mpn = (
            (product.identity.manufacturer_part_number.normalized_value or "")
            if product.identity.manufacturer_part_number
            else str(product.raw_value("Mfg_Part_Num") or "")
        ).strip() or None

        # 1. Process and filter Images
        discovered_images = self._process_images(
            parser.images,
            source_id=source_id,
            verified_domains=verified_domains,
            manufacturer_key=manufacturer_key,
            target_mpn=target_mpn,
            product_id=product.product_id,
        )

        # 2. Process and filter Documents
        discovered_docs = self._process_documents(
            parser.documents,
            source_id=source_id,
            verified_domains=verified_domains,
            manufacturer_key=manufacturer_key,
            target_mpn=target_mpn,
            product_id=product.product_id,
        )

        all_assets = discovered_images + discovered_docs
        return all_assets

    def _extract_jsonld_assets(
        self, data: Any, base_url: str, images_out: list[dict[str, str]]
    ) -> None:
        if isinstance(data, dict):
            img_val = data.get("image") or data.get("images")
            if isinstance(img_val, str):
                images_out.append({
                    "url": urljoin(base_url, img_val),
                    "alt": "jsonld_image",
                    "title": data.get("name", ""),
                })
            elif isinstance(img_val, list):
                for item in img_val:
                    if isinstance(item, str):
                        images_out.append({
                            "url": urljoin(base_url, item),
                            "alt": "jsonld_image",
                            "title": data.get("name", ""),
                        })
            for v in data.values():
                self._extract_jsonld_assets(v, base_url, images_out)
        elif isinstance(data, list):
            for item in data:
                self._extract_jsonld_assets(item, base_url, images_out)

    def _process_images(
        self,
        raw_images: list[dict[str, str]],
        source_id: str,
        verified_domains: tuple[str, ...],
        manufacturer_key: str | None,
        target_mpn: str | None,
        product_id: str,
    ) -> list[DigitalAsset]:
        valid_candidates: list[tuple[float, str, str, str]] = []
        seen_urls: set[str] = set()

        for item in raw_images:
            raw_url = item.get("url", "").strip()
            if not raw_url:
                continue
            clean_url = _clean_url(raw_url)
            if clean_url in seen_urls:
                continue

            # Authority verification
            if not self.verifier.is_authoritative(
                clean_url, verified_domains, manufacturer_key=manufacturer_key
            ):
                continue

            # Check exclusion keywords in URL / alt / title
            url_lower = clean_url.casefold()
            alt_lower = item.get("alt", "").casefold()
            title_lower = item.get("title", "").casefold()

            if any(
                kw in url_lower or kw in alt_lower or kw in title_lower
                for kw in IMAGE_EXCLUSION_KEYWORDS
            ):
                continue

            # Calculate relevance score for primary selection
            score = 1.0
            if "og:image" in alt_lower or "jsonld" in alt_lower:
                score += 5.0
            if target_mpn and target_mpn.casefold() in url_lower:
                score += 3.0
            if any(kw in url_lower for kw in ["zoom", "large", "hi-res", "1000", "main"]):
                score += 2.0

            seen_urls.add(clean_url)
            valid_candidates.append((score, clean_url, item.get("alt", ""), item.get("title", "")))

        # Sort descending by score to pick primary image first
        valid_candidates.sort(key=lambda x: x[0], reverse=True)

        # Enforce budget
        capped = valid_candidates[: self.budget.max_images]
        result: list[DigitalAsset] = []

        for idx, (_, img_url, alt, title) in enumerate(capped):
            asset_type = AssetType.PRIMARY_IMAGE if idx == 0 else AssetType.ALTERNATE_IMAGE
            result.append(
                DigitalAsset(
                    asset_id=f"asset-img-{idx + 1}-{uuid4().hex[:8]}",
                    asset_type=asset_type,
                    uri=img_url,
                    source_id=source_id,
                    title=title or alt or f"Product Image {idx + 1}",
                    filename=Path(urlsplit(img_url).path).name,
                    mime_type="image/jpeg" if img_url.endswith((".jpg", ".jpeg")) else "image/png",
                    manufacturer_domain=_extract_domain(img_url),
                    product_id=product_id,
                    association_scope=AssetAssociationScope.PRODUCT_SPECIFIC.value,
                    content_status=AssetContentStatus.NOT_PARSED.value,
                    status=SourceStatus.AVAILABLE,
                    discovered_from="html_page",
                    description=alt or None,
                )
            )

        return result

    def _process_documents(
        self,
        raw_docs: list[dict[str, str]],
        source_id: str,
        verified_domains: tuple[str, ...],
        manufacturer_key: str | None,
        target_mpn: str | None,
        product_id: str,
    ) -> list[DigitalAsset]:
        valid_docs: list[DigitalAsset] = []
        seen_urls: set[str] = set()

        for item in raw_docs:
            raw_url = item.get("url", "").strip()
            if not raw_url:
                continue
            clean_url = _clean_url(raw_url)
            if clean_url in seen_urls:
                continue

            # Authority verification
            if not self.verifier.is_authoritative(
                clean_url, verified_domains, manufacturer_key=manufacturer_key
            ):
                continue

            seen_urls.add(clean_url)
            title = item.get("title") or item.get("text") or Path(urlsplit(clean_url).path).stem
            anchor_text = item.get("text", "")

            # Classify document type
            doc_type = self.classifier.classify_type(
                clean_url, title=title, anchor_text=anchor_text
            )

            # Determine association scope
            scope = self.classifier.determine_association(
                clean_url,
                target_mpn=target_mpn,
                title=title,
                anchor_text=anchor_text,
                is_catalog=(doc_type == AssetType.CATALOG),
            )

            filename = Path(urlsplit(clean_url).path).name
            valid_docs.append(
                DigitalAsset(
                    asset_id=f"asset-doc-{len(valid_docs) + 1}-{uuid4().hex[:8]}",
                    asset_type=doc_type,
                    uri=clean_url,
                    source_id=source_id,
                    title=title,
                    filename=filename,
                    mime_type="application/pdf" if clean_url.endswith(".pdf") else None,
                    manufacturer_domain=_extract_domain(clean_url),
                    product_id=product_id,
                    association_scope=scope.value,
                    content_status=AssetContentStatus.NOT_PARSED.value,
                    status=SourceStatus.AVAILABLE,
                    discovered_from="html_page",
                    description=anchor_text or None,
                )
            )

            if len(valid_docs) >= self.budget.max_documents:
                break

        return valid_docs

    def attach_to_product(
        self,
        product: ProductTruth,
        assets: list[DigitalAsset],
    ) -> ProductTruth:
        """Attach discovered assets without duplication."""
        existing_uris = {a.uri for a in product.digital_assets}
        for a in assets:
            if a.uri not in existing_uris:
                product.digital_assets.append(a)
                existing_uris.add(a.uri)
        return product


__all__ = [
    "AssetAssociationScope",
    "AssetAuthorityVerifier",
    "AssetBudgetConfig",
    "AssetContentStatus",
    "DigitalAssetDiscoveryService",
    "DISALLOWED_THIRD_PARTY_DOMAINS",
    "DOC_EXTENSIONS",
    "DocumentClassifier",
    "IMAGE_EXCLUSION_KEYWORDS",
    "KNOWN_MANUFACTURER_ASSET_HOSTS",
]
