"""Deterministic structured HTML product evidence extractor.

Extracts rich product specifications, metadata, brand/MPN facts, and digital assets
from JSON-LD, OpenGraph/meta tags, HTML tables, definition lists, and structured
specification layouts without requiring LLM inference.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from unilog_product_intelligence.enrichment.reference import separate_value_and_uom
from unilog_product_intelligence.retrieval.core import (
    EvidenceCandidate,
    EvidenceStatus,
)


@dataclass
class ExtractedField:
    attribute: str
    raw_value: str
    normalized_value: str | None = None
    unit: str | None = None
    source_text: str = ""
    location: dict[str, str] = field(default_factory=dict)
    evidence_type: EvidenceStatus = EvidenceStatus.DIRECT
    confidence: float = 1.0


@dataclass
class ExtractedProductData:
    title: str | None = None
    description: str | None = None
    brand: str | None = None
    manufacturer: str | None = None
    mpn: str | None = None
    sku: str | None = None
    primary_image_url: str | None = None
    gallery_images: list[str] = field(default_factory=list)
    document_urls: list[str] = field(default_factory=list)
    specifications: list[ExtractedField] = field(default_factory=list)
    features: list[str] = field(default_factory=list)


class _StructuredHTMLParser(HTMLParser):
    """Parses HTML into structured tables, definition lists, spec blocks, metadata, and JSON-LD."""

    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "nav", "footer"}

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.title = ""
        self.meta: dict[str, str] = {}
        self.jsonld_raw: list[str] = []
        self.tables: list[list[list[str]]] = []  # list of tables: rows -> cols
        self.dl_pairs: list[tuple[str, str]] = []
        self.spec_div_pairs: list[tuple[str, str]] = []
        self.feature_bullets: list[str] = []
        self.images: list[str] = []
        self.documents: list[str] = []

        # Internal state tracking
        self._skip_depth = 0
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_buf: list[str] = []

        # Table tracking
        self._in_table = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []

        # DL tracking
        self._current_dt: list[str] = []
        self._current_dd: list[str] = []
        self._last_dt_text: str | None = None

        # Spec section / div tracking
        self._spec_depth = 0
        self._in_spec_section = False
        self._current_li: list[str] = []
        self._in_li = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.casefold(): (v or "") for k, v in attrs if k}

        if tag == "script":
            script_type = attr_dict.get("type", "").casefold()
            if script_type == "application/ld+json":
                self._in_jsonld = True
            else:
                self._skip_depth += 1
            return

        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        if tag == "title":
            self._in_title = True
            return

        if tag == "meta":
            prop = attr_dict.get("property") or attr_dict.get("name")
            content = attr_dict.get("content")
            if prop and content:
                self.meta[prop.casefold().strip()] = content.strip()
            return

        # Check for spec section indicators
        class_id_str = f"{attr_dict.get('class', '')} {attr_dict.get('id', '')}".casefold()
        spec_markers = ("spec", "technical", "tech-data", "detail", "attribute", "feature")
        if any(marker in class_id_str for marker in spec_markers):
            self._in_spec_section = True
            self._spec_depth += 1

        # Table handling
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif tag == "tr" and self._in_table:
            self._current_row = []
        elif tag in {"td", "th"} and self._in_table:
            self._current_cell = []

        # DL handling
        elif tag == "dt":
            self._in_dt = True
            self._in_dd = False
            self._current_dt = []
            self._last_dt_text = None
        elif tag == "dd":
            self._in_dt = False
            self._in_dd = True
            self._current_dd = []

        # List items in spec sections
        elif tag == "li":
            self._in_li = True
            self._current_li = []

        # Image extraction
        elif tag == "img":
            src = (
                attr_dict.get("src")
                or attr_dict.get("data-src")
                or attr_dict.get("data-original")
            )
            if src:
                full_img = urljoin(self.base_url, src.strip())
                self.images.append(full_img)

        # Document extraction
        elif tag == "a":
            href = attr_dict.get("href", "").strip()
            if href:
                full_href = urljoin(self.base_url, href)
                lower_href = full_href.casefold()
                doc_exts = (".pdf", ".dwg", ".sds", ".dxf", ".step", ".stp")
                if any(lower_href.endswith(ext) for ext in doc_exts):
                    self.documents.append(full_href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_jsonld:
            raw = "".join(self._jsonld_buf).strip()
            if raw:
                self.jsonld_raw.append(raw)
            self._jsonld_buf = []
            self._in_jsonld = False
            return

        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if self._skip_depth > 0:
            return

        if tag == "title":
            self._in_title = False
            return

        if tag == "table" and self._in_table:
            if self._current_table:
                self.tables.append(self._current_table)
            self._in_table = False
            self._current_table = []
        elif tag == "tr" and self._in_table:
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = []
        elif tag in {"td", "th"} and self._in_table:
            cell_text = " ".join(self._current_cell).strip()
            self._current_row.append(cell_text)
            self._current_cell = []

        elif tag == "dt":
            self._last_dt_text = " ".join(self._current_dt).strip()
            self._current_dt = []
            self._in_dt = False
        elif tag == "dd":
            dd_text = " ".join(self._current_dd).strip()
            if self._last_dt_text and dd_text:
                self.dl_pairs.append((self._last_dt_text, dd_text))
            self._last_dt_text = None
            self._current_dd = []
            self._in_dd = False

        elif tag == "li" and self._in_li:
            li_text = " ".join(self._current_li).strip()
            if li_text and self._in_spec_section and len(li_text) < 300:
                self.feature_bullets.append(li_text)
            self._in_li = False
            self._current_li = []

        if self._in_spec_section and self._spec_depth > 0 and tag in {"div", "section", "article"}:
            self._spec_depth -= 1
            if self._spec_depth <= 0:
                self._in_spec_section = False

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return

        if self._skip_depth > 0:
            return

        clean = re.sub(r"\s+", " ", data).strip()
        if not clean:
            return

        if self._in_title:
            self.title += (" " if self.title else "") + clean
            return

        if self._in_table:
            self._current_cell.append(clean)
            return

        if getattr(self, "_in_dt", False):
            self._current_dt.append(clean)
        elif getattr(self, "_in_dd", False):
            self._current_dd.append(clean)

        if self._in_li:
            self._current_li.append(clean)


class HtmlProductEvidenceExtractor:
    """Extracts structured product evidence from HTML documents deterministically."""

    # Common canonical attribute label mappings for industrial / tools products
    LABEL_SYNONYMS: dict[str, str] = {
        "diameter": "Diameter",
        "disc diameter": "Diameter",
        "wheel diameter": "Diameter",
        "blade diameter": "Diameter",
        "size": "Size",
        "arbor": "Arbor Size",
        "arbor size": "Arbor Size",
        "arbor diameter": "Arbor Size",
        "thickness": "Thickness",
        "wheel thickness": "Thickness",
        "blade thickness": "Thickness",
        "kerf": "Kerf",
        "grit": "Grit",
        "grit size": "Grit",
        "material": "Material",
        "abrasive material": "Material",
        "backing material": "Backing Material",
        "package quantity": "Package Quantity",
        "pack qty": "Package Quantity",
        "pkg qty": "Package Quantity",
        "quantity": "Package Quantity",
        "pieces": "Package Quantity",
        "piece count": "Package Quantity",
        "max rpm": "Maximum RPM",
        "maximum rpm": "Maximum RPM",
        "max speed": "Maximum RPM",
        "length": "Length",
        "width": "Width",
        "height": "Height",
        "weight": "Weight",
        "color": "Color",
        "voltage": "Voltage",
        "amperage": "Amperage",
        "battery type": "Battery Type",
        "country of origin": "Country of Origin",
    }

    # Negative filters for junk labels
    IGNORE_LABELS = {
        "cart", "checkout", "shipping", "reviews", "search", "menu", "login",
        "account", "privacy", "terms", "cookie", "copyright", "home", "contact",
        "share", "email", "print", "facebook", "twitter", "instagram", "youtube",
    }

    def extract(
        self,
        html_text: str,
        base_url: str,
        source_id: str = "",
    ) -> ExtractedProductData:
        """Parse HTML string into an ExtractedProductData container."""
        parser = _StructuredHTMLParser(base_url)
        parser.feed(html_text)
        parser.close()

        data = ExtractedProductData()

        # 1. Parse JSON-LD blocks
        for raw_json in parser.jsonld_raw:
            try:
                parsed_json = json.loads(raw_json)
                self._extract_jsonld(parsed_json, data, base_url)
            except Exception:
                continue

        # 2. Extract OpenGraph & Meta fallbacks
        self._extract_meta(parser.meta, parser.title, data, base_url)

        # 3. Extract HTML specification tables
        self._extract_tables(parser.tables, data)

        # 4. Extract Definition Lists
        self._extract_dl(parser.dl_pairs, data)

        # 5. Extract Feature Bullets
        for bullet in parser.feature_bullets:
            clean_b = unescape(bullet).strip()
            if 10 < len(clean_b) < 300 and clean_b not in data.features:
                data.features.append(clean_b)

        # 6. Extract Images & Documents
        for img in parser.images:
            if self._is_valid_product_image(img) and img not in data.gallery_images:
                data.gallery_images.append(img)
                if not data.primary_image_url:
                    data.primary_image_url = img

        for doc in parser.documents:
            if doc not in data.document_urls:
                data.document_urls.append(doc)

        return data

    def extract_evidence_candidates(
        self,
        html_text: str,
        base_url: str,
        source_id: str = "",
    ) -> list[EvidenceCandidate]:
        """Convert extracted structured product data into a list of EvidenceCandidate objects."""
        data = self.extract(html_text, base_url, source_id)
        candidates: list[EvidenceCandidate] = []

        if data.title:
            candidates.append(
                EvidenceCandidate(
                    attribute="Product Title",
                    raw_value=data.title,
                    normalized_candidate=data.title,
                    source_id=source_id,
                    url=base_url,
                    source_text=f"Product Title: {data.title}",
                    location={"html_source": "title_or_jsonld"},
                    evidence_type=EvidenceStatus.DIRECT,
                    status=EvidenceStatus.DIRECT,
                    model_confidence=1.0,
                )
            )

        if data.description:
            candidates.append(
                EvidenceCandidate(
                    attribute="Product Description",
                    raw_value=data.description,
                    normalized_candidate=data.description,
                    source_id=source_id,
                    url=base_url,
                    source_text=f"Product Description: {data.description[:500]}",
                    location={"html_source": "meta_or_jsonld"},
                    evidence_type=EvidenceStatus.DIRECT,
                    status=EvidenceStatus.DIRECT,
                    model_confidence=0.95,
                )
            )

        if data.brand:
            candidates.append(
                EvidenceCandidate(
                    attribute="Brand",
                    raw_value=data.brand,
                    normalized_candidate=data.brand,
                    source_id=source_id,
                    url=base_url,
                    source_text=f"Brand: {data.brand}",
                    location={"html_source": "jsonld_brand"},
                    evidence_type=EvidenceStatus.DIRECT,
                    status=EvidenceStatus.DIRECT,
                    model_confidence=1.0,
                )
            )

        if data.mpn:
            candidates.append(
                EvidenceCandidate(
                    attribute="Manufacturer Part Number",
                    raw_value=data.mpn,
                    normalized_candidate=data.mpn,
                    source_id=source_id,
                    url=base_url,
                    source_text=f"MPN: {data.mpn}",
                    location={"html_source": "jsonld_mpn"},
                    evidence_type=EvidenceStatus.DIRECT,
                    status=EvidenceStatus.DIRECT,
                    model_confidence=1.0,
                )
            )

        # Specifications
        for spec in data.specifications:
            candidates.append(
                EvidenceCandidate(
                    attribute=spec.attribute,
                    raw_value=spec.raw_value,
                    normalized_candidate=spec.normalized_value or spec.raw_value,
                    unit=spec.unit,
                    source_id=source_id,
                    url=base_url,
                    source_text=spec.source_text,
                    location=spec.location,
                    evidence_type=spec.evidence_type,
                    status=spec.evidence_type,
                    model_confidence=spec.confidence,
                )
            )

        # Feature bullets
        if data.features:
            features_joined = "; ".join(data.features[:15])
            candidates.append(
                EvidenceCandidate(
                    attribute="Product Features",
                    raw_value=features_joined,
                    normalized_candidate=features_joined,
                    source_id=source_id,
                    url=base_url,
                    source_text=f"Features: {features_joined}",
                    location={"html_source": "feature_bullets"},
                    evidence_type=EvidenceStatus.DIRECT,
                    status=EvidenceStatus.DIRECT,
                    model_confidence=0.9,
                )
            )

        return candidates

    def _extract_jsonld(self, obj: Any, data: ExtractedProductData, base_url: str) -> None:
        """Recursively inspect JSON-LD structure for Product schema."""
        if isinstance(obj, list):
            for item in obj:
                self._extract_jsonld(item, data, base_url)
            return

        if not isinstance(obj, dict):
            return

        # Check @graph
        if "@graph" in obj and isinstance(obj["@graph"], list):
            for item in obj["@graph"]:
                self._extract_jsonld(item, data, base_url)

        type_val = str(obj.get("@type", "")).casefold()
        if any(pt in type_val for pt in ("product", "productgroup", "individualproduct")):
            if not data.title and "name" in obj:
                data.title = str(obj["name"]).strip()
            if not data.description and "description" in obj:
                data.description = str(obj["description"]).strip()
            if not data.mpn and "mpn" in obj:
                data.mpn = str(obj["mpn"]).strip()
            if not data.sku and "sku" in obj:
                data.sku = str(obj["sku"]).strip()

            # Brand extraction
            if not data.brand and "brand" in obj:
                b_val = obj["brand"]
                if isinstance(b_val, dict):
                    b_name = b_val.get("name") or b_val.get("legalName") or ""
                    data.brand = str(b_name).strip() or None
                elif isinstance(b_val, str):
                    data.brand = b_val.strip() or None

            # Manufacturer extraction
            if not data.manufacturer and "manufacturer" in obj:
                m_val = obj["manufacturer"]
                if isinstance(m_val, dict):
                    data.manufacturer = str(m_val.get("name") or "").strip() or None
                elif isinstance(m_val, str):
                    data.manufacturer = m_val.strip() or None

            # Image extraction from JSON-LD Product
            if "image" in obj:
                img_val = obj["image"]
                if isinstance(img_val, str) and img_val.strip():
                    full_img = urljoin(base_url, img_val.strip())
                    if not data.primary_image_url:
                        data.primary_image_url = full_img
                    if full_img not in data.gallery_images:
                        data.gallery_images.append(full_img)
                elif isinstance(img_val, list):
                    for img_item in img_val:
                        if isinstance(img_item, str) and img_item.strip():
                            full_img = urljoin(base_url, img_item.strip())
                            if not data.primary_image_url:
                                data.primary_image_url = full_img
                            if full_img not in data.gallery_images:
                                data.gallery_images.append(full_img)
                        elif isinstance(img_item, dict):
                            u = img_item.get("url") or img_item.get("contentUrl")
                            if u:
                                full_img = urljoin(base_url, str(u).strip())
                                if not data.primary_image_url:
                                    data.primary_image_url = full_img
                                if full_img not in data.gallery_images:
                                    data.gallery_images.append(full_img)
                elif isinstance(img_val, dict):
                    u = img_val.get("url") or img_val.get("contentUrl")
                    if u:
                        full_img = urljoin(base_url, str(u).strip())
                        if not data.primary_image_url:
                            data.primary_image_url = full_img
                        if full_img not in data.gallery_images:
                            data.gallery_images.append(full_img)

            # additionalProperty extraction (KeyValue specs in JSON-LD)
            if "additionalProperty" in obj:
                props = obj["additionalProperty"]
                if isinstance(props, list):
                    for prop in props:
                        if isinstance(prop, dict):
                            name = str(prop.get("name") or "").strip()
                            val = str(prop.get("value") or "").strip()
                            if name and val:
                                self._add_spec_pair(
                                    name, val, data, location={"jsonld_prop": name}
                                )

    def _extract_meta(
        self,
        meta: dict[str, str],
        html_title: str,
        data: ExtractedProductData,
        base_url: str,
    ) -> None:
        """Extract OpenGraph and meta tag attributes."""
        if not data.title:
            t_cand = meta.get("og:title") or html_title.split("|")[0].split(" - ")[0].strip()
            data.title = t_cand or None
        if not data.description:
            data.description = meta.get("og:description") or meta.get("description") or None
        if not data.brand and "product:brand" in meta:
            data.brand = meta["product:brand"].strip() or None

        og_img = (
            meta.get("og:image")
            or meta.get("og:image:secure_url")
            or meta.get("twitter:image")
        )
        if og_img and self._is_valid_product_image(og_img):
            full_og = urljoin(base_url, og_img.strip())
            if not data.primary_image_url:
                data.primary_image_url = full_og
            if full_og not in data.gallery_images:
                data.gallery_images.append(full_og)

    def _extract_tables(self, tables: list[list[list[str]]], data: ExtractedProductData) -> None:
        """Extract label/value pairs from 2-column or structured specification tables."""
        for table in tables:
            for row in table:
                if len(row) == 2:
                    label, val = row[0].strip(), row[1].strip()
                    if label and val:
                        self._add_spec_pair(label, val, data, location={"source": "html_table"})
                elif len(row) > 2 and ":" in row[0]:
                    parts = row[0].split(":", 1)
                    label, val = parts[0].strip(), parts[1].strip()
                    if label and val:
                        self._add_spec_pair(
                            label, val, data, location={"source": "html_table_row"}
                        )

    def _extract_dl(self, dl_pairs: list[tuple[str, str]], data: ExtractedProductData) -> None:
        """Extract label/value pairs from definition lists."""
        for label, val in dl_pairs:
            if label and val:
                self._add_spec_pair(label, val, data, location={"source": "html_dl"})

    def _add_spec_pair(
        self,
        label: str,
        raw_value: str,
        data: ExtractedProductData,
        location: dict[str, str] | None = None,
    ) -> None:
        """Normalize attribute label, separate value/UOM, and record extracted specification."""
        clean_label = re.sub(r"[:\s]+$", "", unescape(label)).strip()
        clean_val = unescape(raw_value).strip()

        if not clean_label or not clean_val or len(clean_label) > 60 or len(clean_val) > 300:
            return

        label_lower = clean_label.casefold()
        if any(ign in label_lower for ign in self.IGNORE_LABELS):
            return

        # Canonicalize label if in known synonym dictionary
        canonical_label = self.LABEL_SYNONYMS.get(label_lower, clean_label.title())

        # Perform value & UOM separation
        norm_val, uom = separate_value_and_uom(clean_val)

        # Check if already extracted
        if any(s.attribute.casefold() == canonical_label.casefold() for s in data.specifications):
            return

        is_table = location and "table" in str(location)
        ev_type = EvidenceStatus.TABLE if is_table else EvidenceStatus.DIRECT
        data.specifications.append(
            ExtractedField(
                attribute=canonical_label,
                raw_value=clean_val,
                normalized_value=norm_val,
                unit=uom,
                source_text=f"{canonical_label}: {clean_val}",
                location=location or {},
                evidence_type=ev_type,
                confidence=0.95,
            )
        )

    @staticmethod
    def _is_valid_product_image(url: str) -> bool:
        """Reject non-product images such as logos, icons, badges, banners, and sprites."""
        u_lower = url.casefold()
        valid_exts = (".jpg", ".jpeg", ".png", ".webp")
        if not any(u_lower.endswith(ext) or ext in u_lower for ext in valid_exts):
            return False
        reject_keywords = (
            "logo", "icon", "badge", "sprite", "banner", "pixel", "tracking",
            "social", "cart", "header", "footer", "favicon", "placeholder",
            "arrow", "star-rating", "flag",
        )
        return not any(rej in u_lower for rej in reject_keywords)


__all__ = [
    "ExtractedField",
    "ExtractedProductData",
    "HtmlProductEvidenceExtractor",
]
