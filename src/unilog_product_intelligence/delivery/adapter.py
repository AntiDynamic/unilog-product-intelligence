"""Boundary from Phase65Result to the observed UniHack delivery contract.

This adapter synthesizes all 252 delivery columns from:
  - Raw input passthrough (6 input columns)
  - Resolved identity (MANUFACTURER_NAME, BRAND_NAME, etc.)
  - ProductTruth classification (Dept, Class, Fine, Classpath)
  - ProductTruth descriptions (SHORT_DESC, LONG_DESC1, features, etc.)
  - Enriched attributes (attribute triplets, dimensions, identifiers)
  - Digital assets (images, documents)
  - Phase65 source URLs (MFR URL, Ref URLs)

Fabrication is strictly forbidden: every non-empty value must be traceable to
either a raw input field, a retrieved manufacturer source, or an AI-extracted
evidence candidate that has been validated by the enrichment pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.domain.truth import AssetType, ProductTruth


class DeliveryMappingPending(RuntimeError):
    """Raised when exact official delivery headers are unavailable."""


class DeliverySchemaContract(BaseModel):
    """Observed official header contract; empty means mapping is intentionally blocked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool = False
    source_file: str | None = None
    headers: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, path: str | Path) -> DeliverySchemaContract:
        """Load an exact header contract extracted from the supplied template."""

        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        headers = tuple(payload.get("headers", ()))
        return cls(
            available=bool(headers),
            source_file=str(payload.get("source_file", source)),
            headers=headers,
        )


class UniHackDeliveryRecord(BaseModel):
    """A delivery-shaped record created only from an observed official contract."""

    model_config = ConfigDict(extra="forbid")

    headers: tuple[str, ...]
    values: dict[str, Any] = Field(default_factory=dict)

    def as_row(self) -> list[Any]:
        """Return values in the exact observed header order."""

        return [self.values.get(header) for header in self.headers]


class ProductTruthDeliveryAdapter:
    """Isolated adapter that maps only source fields sharing observed headers.

    Kept for backwards compatibility. Use Phase65ResultDeliveryAdapter for full
    252-column output.
    """

    def __init__(self, contract: DeliverySchemaContract) -> None:
        self.contract = contract

    def to_record(self, product: ProductTruth) -> UniHackDeliveryRecord:
        """Map raw source values only when their names occur in the observed contract."""

        if not self.contract.available or not self.contract.headers:
            raise DeliveryMappingPending(
                "Exact UniHack delivery mapping is blocked until the official CSV is available."
            )
        values = {
            field.field_name: field.raw_value
            for field in product.raw_inputs
            if field.field_name in self.contract.headers
        }
        return UniHackDeliveryRecord(headers=self.contract.headers, values=values)


# ── Full 252-column adapter ───────────────────────────────────────────────────


class Phase65ResultDeliveryAdapter:
    """Maps a Phase65Result to the complete 252-column UniHack delivery format.

    This is the primary adapter for end-to-end pipeline output.  It synthesizes
    all required columns from the enriched ProductTruth, Phase 5 source records,
    and Phase 6 enrichment candidates.

    No values are fabricated: any column that cannot be derived from evidence
    is left as None (which serialises to an empty CSV cell).
    """

    # Maximum attribute triplets in the delivery format
    MAX_ATTRIBUTES = 50
    # Maximum item feature bullets
    MAX_FEATURES = 20
    # Maximum reference URLs (beyond MFR URL)
    MAX_REF_URLS = 5
    # Maximum alternate images
    MAX_ALT_IMAGES = 4

    def __init__(self, contract: DeliverySchemaContract) -> None:
        self.contract = contract

    def to_record(
        self,
        phase65_result: Any,  # Phase65Result — avoid circular import
    ) -> UniHackDeliveryRecord:
        """Map Phase65Result → UniHackDeliveryRecord with all 252 columns populated."""

        if not self.contract.available or not self.contract.headers:
            raise DeliveryMappingPending(
                "Delivery schema not loaded. Call DeliverySchemaContract.from_json() first."
            )

        product = phase65_result.product_truth
        values: dict[str, Any] = {}

        # ── 1. Source URL columns ─────────────────────────────────────────────
        mfr_url, ref_urls = _extract_source_urls(phase65_result, product)
        values["MFR URL"] = mfr_url
        for i in range(1, self.MAX_REF_URLS + 1):
            values[f"Ref URL {i}"] = (
                ref_urls[i - 1] if i - 1 < len(ref_urls) else None
            )

        # ── 2. Raw input passthrough ──────────────────────────────────────────
        raw = {f.field_name: f.raw_value for f in product.raw_inputs}
        raw_cols = (
            "Mfg_Part_Num", "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf"
        )
        for col in raw_cols:
            values[col] = raw.get(col)

        # ── 3. Identity columns ───────────────────────────────────────────────
        identity = product.identity
        attr_by_name = {
            a.canonical_name.casefold(): a for a in product.attributes if a.canonical_name
        }

        # Resolve manufacturer: prefer resolved manufacturer if distributor-masked,
        # otherwise identity manufacturer (cleaned of account code suffixes),
        # then enriched attribute.
        # CRITICAL: Distributor names must NEVER be published as MANUFACTURER_NAME.
        is_dist = getattr(phase65_result, "is_distributor_masked", False)
        res_mfg = _resolved_manufacturer(phase65_result)

        mfg_name: str | None = None
        if is_dist:
            if res_mfg and not _is_distributor_string(res_mfg):
                mfg_name = res_mfg
            else:
                enriched_mfg = _attr_value(
                    attr_by_name, "manufacturer", "manufacturer name"
                )
                if enriched_mfg and not _is_distributor_string(enriched_mfg):
                    mfg_name = enriched_mfg
                else:
                    mfg_name = None
        else:
            ident_mfg = _ident(identity, "manufacturer")
            if ident_mfg and not _is_distributor_string(ident_mfg):
                mfg_name = ident_mfg
            elif res_mfg and not _is_distributor_string(res_mfg):
                mfg_name = res_mfg
            else:
                enriched_mfg = _attr_value(
                    attr_by_name, "manufacturer", "manufacturer name"
                )
                if enriched_mfg and not _is_distributor_string(enriched_mfg):
                    mfg_name = enriched_mfg
                else:
                    mfg_name = None

        values["MANUFACTURER_NAME"] = _clean_name(mfg_name)

        # Resolve brand: prefer enriched attribute (e.g. from Diablo product page),
        # then non-placeholder identity brand, then resolved brand.
        # CRITICAL: Distributor names must NEVER be published as BRAND_NAME.
        brand_attr = _attr_value(attr_by_name, "brand", "brand name")
        brand_ident = _ident(identity, "brand")
        brand_res = _resolved_brand(phase65_result)

        brand_candidate: str | None = None
        for b in (brand_attr, brand_ident, brand_res):
            if b and not _is_distributor_string(b) and b.casefold() not in _PLACEHOLDER_VALUES:
                brand_candidate = b
                break

        values["BRAND_NAME"] = _clean_name(brand_candidate)
        values["TRADE_NAME"] = _ident(identity, "trade_name")
        values["MANUFACTURER_PART_NUMBER"] = (
            _attr_value(attr_by_name, "manufacturer part number", "mpn")
            or _ident(identity, "manufacturer_part_number")
            or raw.get("Mfg_Part_Num")
        )
        values["ALTERNATE_PART_NUMBER"] = _ident(identity, "source_part_number")

        # ── 4. Classification columns ─────────────────────────────────────────
        cls = product.classification
        values["Dept"] = cls.department
        values["Class"] = cls.class_name
        values["Fine"] = cls.fine
        values["Classpath"] = " > ".join(cls.classpath) if cls.classpath else None

        # ── 5. Description columns ────────────────────────────────────────────
        desc = product.descriptions
        values["MOBILE_DESC"] = desc.mobile if desc else None
        values["INVOICE_DESC"] = desc.invoice if desc else None
        values["SHORT_DESC"] = desc.short if desc else None
        values["LONG_DESC1"] = desc.long if desc else None
        values["RETAIL_DESC"] = desc.retail if desc else None
        values["MARKETING_DESCRIPTION"] = (
            (desc.marketing or desc.retail or desc.long) if desc else None
        )

        # ── 6. Item feature bullets ───────────────────────────────────────────
        features = desc.features if desc else []
        for i in range(1, self.MAX_FEATURES + 1):
            values[f"ITEM_FEATURES_{i}"] = (
                features[i - 1] if i - 1 < len(features) else None
            )

        # ── 7. Attribute triplets (LABEL / VALUE / UOM × 50) ─────────────────
        attr_candidates = _build_attribute_triplets(product)
        for i in range(1, self.MAX_ATTRIBUTES + 1):
            if i - 1 < len(attr_candidates):
                label, value, uom = attr_candidates[i - 1]
            else:
                label, value, uom = None, None, None
            values[f"ATTRIBUTE_LABEL {i}"] = label
            values[f"ATTRIBUTE_VALUE {i}"] = value
            values[f"ATTRIBUTE_UOM {i}"] = uom

        # ── 8. Attribute-keyed special fields ─────────────────────────────────
        attr_by_name = {
            a.canonical_name.casefold(): a for a in product.attributes if a.canonical_name
        }
        values["With"] = _attr_value(
            attr_by_name,
            "with",
            "includes",
            "package contents",
            "accessories included",
            "items included",
            "package includes",
            "what's included",
            "contents",
        )
        values["Standard/Approvals"] = _attr_value(
            attr_by_name,
            "standard/approvals",
            "standards/approvals",
            "standards",
            "approvals",
            "certifications",
            "compliance",
            "agency approvals",
            "safety listing",
            "listing",
            "certifications / approvals",
            "standards / approvals",
            "ul listing",
            "ul listed",
            "csa certified",
            "energy star",
            "ansi",
            "astm",
        )
        values["Prop 65"] = _attr_value(attr_by_name, "prop 65", "proposition 65", "prop65")
        values["Application"] = _attr_value(attr_by_name, "application")
        values["Includes"] = _attr_value(
            attr_by_name,
            "includes",
            "what's included",
            "box contents",
            "package contents",
            "with",
        )
        values["Product Name"] = _attr_value(
            attr_by_name, "product name", "name", "product title"
        )

        # ── 9. Identifier columns ─────────────────────────────────────────────
        values["UPC"] = _attr_value(attr_by_name, "upc")
        values["EAN"] = _attr_value(attr_by_name, "ean")
        values["GTIN"] = _attr_value(attr_by_name, "gtin")
        values["UNSPSC"] = _attr_value(attr_by_name, "unspsc")

        # ── 10. Commercial columns ────────────────────────────────────────────
        values["Warranty"] = _attr_value(attr_by_name, "warranty")
        values["List Price"] = _attr_value(attr_by_name, "list price", "price")
        values["Selling Qty"] = _attr_value(attr_by_name, "selling qty", "quantity")
        values["Selling UOM"] = _attr_value(attr_by_name, "selling uom", "unit of measure")
        values["Standard Packaging Information"] = _attr_value(
            attr_by_name, "standard packaging information", "packaging", "package quantity"
        )

        # ── 11. Dimension columns ─────────────────────────────────────────────
        for dim_col, *aliases in [
            ("LENGTH", "length"),
            ("HEIGHT", "height"),
            ("WIDTH", "width"),
            ("WEIGHT", "weight"),
            ("VOLUME", "volume"),
        ]:
            attr = _find_attr(attr_by_name, dim_col.lower(), *aliases)
            if attr is not None:
                values[dim_col] = _best_value(attr)
                values[f"{dim_col}_UOM"] = attr.uom
            else:
                values[dim_col] = None
                values[f"{dim_col}_UOM"] = None

        # ── 12. Digital asset columns ─────────────────────────────────────────
        image_types = {AssetType.IMAGE, AssetType.PRIMARY_IMAGE, AssetType.ALTERNATE_IMAGE}
        images = [a for a in product.digital_assets if a.asset_type in image_types]
        sds_assets = [a for a in product.digital_assets if a.asset_type == AssetType.SDS]
        doc_assets = [a for a in product.digital_assets if a.asset_type not in image_types]

        values["Product Image"] = images[0].uri if images else None
        for i in range(1, self.MAX_ALT_IMAGES + 1):
            values[f"Alternate Image {i}"] = images[i].uri if i < len(images) else None

        values["SDS"] = sds_assets[0].uri if sds_assets else None
        values["SDS_1"] = sds_assets[1].uri if len(sds_assets) > 1 else None

        # Document type mapping by title keyword
        _assign_doc(values, doc_assets, "Warranty Information", ("warranty",))
        _assign_doc(values, doc_assets, "Catalog", ("catalog", "catalogue"))
        _assign_doc(
            values, doc_assets, "Specification Sheet",
            ("spec", "specification", "technical")
        )
        _assign_doc(
            values, doc_assets, "Instruction/Installation Manual",
            ("install", "instruction", "setup")
        )
        _assign_doc(values, doc_assets, "Service Manual", ("service manual",))
        _assign_doc(
            values, doc_assets, "Owners/User Manual", ("owner", "user manual", "user guide")
        )
        _assign_doc(
            values, doc_assets, "Line Drawing", ("line drawing", "dimensional drawing", "cad")
        )
        _assign_doc(values, doc_assets, "MTR", ("mtr", "mill test", "material test"))
        _assign_doc(values, doc_assets, "RoHS", ("rohs",))
        _assign_doc(
            values, doc_assets, "Full Engineering Drawing", ("engineering drawing", "full drawing")
        )
        _assign_doc(values, doc_assets, "Energy Star Guide", ("energy star",))
        _assign_doc(
            values, doc_assets, "Technical Bulletin", ("technical bulletin", "tech bulletin")
        )
        _assign_doc(values, doc_assets, "Submittal", ("submittal",))
        _assign_doc(values, doc_assets, "Compatibility Chart", ("compatibility",))
        _assign_doc(values, doc_assets, "Size Chart", ("size chart",))
        _assign_doc(values, doc_assets, "Product Label/Insert", ("label", "insert"))
        _assign_doc(values, doc_assets, "Video Link", ("video", "youtube", "vimeo"))
        _assign_doc(values, doc_assets, "Video Link 1", ("video link 1",))

        # ── 13. Meta columns ──────────────────────────────────────────────────
        values["Country Of Origin"] = _attr_value(
            attr_by_name, "country of origin", "origin", "made in"
        )
        values["Discontinued"] = _attr_value(attr_by_name, "discontinued")
        values["Actual Image (Yes/No)"] = "Yes" if values.get("Product Image") else "No"

        # ── 14. Internal system IDs (left blank — not in our scope) ──────────
        values["PART_NUMBER"] = None
        values["SKU - MY_PART_NUMBER"] = None

        return UniHackDeliveryRecord(headers=self.contract.headers, values=values)


_PLACEHOLDER_VALUES = {
    "",
    "-",
    "-- unbranded --",
    "-- no unilog brand --",
    "-- no dib brand --",
    "-- unassigned --",
    "none",
    "n/a",
    "null",
}


def _is_distributor_string(name: str | None) -> bool:
    """Return True if name matches known distributor fragments or codes."""
    if not name:
        return False
    lower = name.casefold()
    dist_fragments = (
        "supply",
        "dealer",
        "dealers",
        "cooperative",
        "co-op",
        "coop",
        "distributor",
        "distribution",
        "industrial",
        "wholesale",
        "warehouse",
        "lumber",
        "hardware",
        "electric supply",
        "electrical supply",
        "plumbing supply",
        "building supply",
        "direct supply",
        "janitor",
        "maintenance",
        "procurement",
        "appliance dealers",
        "builders firstsource",
        "boise cascade",
        "parksite",
        "u s lumber",
        "jam industrial",
        "l & w supply",
        "cameron ashley",
        "grainger",
        "ferguson",
        "fastenal",
        "orgill",
        "true value",
        "do it best",
        "abc supply",
    )
    return any(f in lower for f in dist_fragments)


def _ident(identity: Any, field: str) -> str | None:
    """Extract a non-placeholder string from an IdentityField on ProductIdentity."""
    f = getattr(identity, field, None)
    if f is None:
        return None
    val = str(f.normalized_value or f.raw_value or "").strip()
    if not val or val.casefold() in _PLACEHOLDER_VALUES:
        return None
    return val


def _clean_name(name: str | None) -> str | None:
    """Remove account number suffixes like '(2435)' or trailing whitespace."""
    if not name:
        return None
    import re
    cleaned = re.sub(r"\s*\(\d{2,8}\)\s*$", "", name).strip()
    return cleaned or name


def _resolved_manufacturer(result: Any) -> str | None:
    """Best-effort manufacturer name from Phase65Result metadata."""
    val = getattr(result, "resolved_manufacturer", None)
    if val and str(val).casefold() not in _PLACEHOLDER_VALUES:
        return str(val)
    return None


def _resolved_brand(result: Any) -> str | None:
    """Brand from Phase65Result — populated when brand resolver ran."""
    val = getattr(result, "resolved_brand", None)
    if val and str(val).casefold() not in _PLACEHOLDER_VALUES:
        return str(val)
    return None


def _rank_document_url(url: str) -> int:
    """Rank document URL priority: lower value = higher priority.

    Priority order:
    1. Installation / User Manuals
    2. Specification sheets / Datasheets / Brochures
    3. Technical documentation / Wiring diagrams / Service
    4. Warranty documents
    5. General PDFs / documents
    """
    u = url.casefold()
    if any(
        k in u
        for k in (
            "manual",
            "install",
            "user-guide",
            "user_guide",
            "owner",
            "use-and-care",
            "instruction",
            "setup",
        )
    ):
        return 1
    if any(k in u for k in ("spec", "datasheet", "brochure", "cutsheet", "catalog")):
        return 2
    if any(
        k in u
        for k in (
            "tech",
            "wiring",
            "diagram",
            "service",
            "bulletin",
            "engineering",
            "drawing",
        )
    ):
        return 3
    if any(k in u for k in ("warranty", "guarantee")):
        return 4
    if u.endswith(".pdf") or "document" in u or "download" in u or "/pdf" in u:
        return 5
    return 6


def _extract_source_urls(
    result: Any, product: ProductTruth
) -> tuple[str | None, list[str]]:
    """Extract MFR URL and ranked reference/document URLs from result and truth."""
    mfr_url: str | None = None
    candidate_urls: list[str] = []

    # 1. Prefer ProductEvidencePacket if present on Phase65Result
    packet = getattr(result, "evidence_packet", None)
    source_ctx = None
    if packet is not None and type(packet).__name__ == "ProductEvidencePacket":
        raw_pkt_url = getattr(packet, "canonical_product_url", None)
        if isinstance(raw_pkt_url, str) and raw_pkt_url.strip():
            mfr_url = raw_pkt_url.strip()
        source_ctx = getattr(packet, "source_context", None)
        if not mfr_url and source_ctx:
            raw_ctx_url = getattr(source_ctx, "canonical_product_url", None)
            if isinstance(raw_ctx_url, str) and raw_ctx_url.strip():
                mfr_url = raw_ctx_url.strip()
        doc_urls = getattr(packet, "document_urls", None)
        if isinstance(doc_urls, (list, tuple)):
            for doc_url in doc_urls:
                if isinstance(doc_url, str) and doc_url.strip() and doc_url.strip() != mfr_url:
                    candidate_urls.append(doc_url.strip())
    else:
        # Fallback to legacy manufacturer_job / verified_source_context
        job = getattr(result, "manufacturer_job", None)
        source_ctx = getattr(job, "verified_source_context", None) if job else None
        if source_ctx:
            raw_ctx_url = getattr(source_ctx, "canonical_product_url", None)
            if isinstance(raw_ctx_url, str) and raw_ctx_url.strip():
                mfr_url = raw_ctx_url.strip()

        if job and not mfr_url:
            ctx_urls = getattr(job, "url_context_urls", ()) or ()
            if isinstance(ctx_urls, (list, tuple)):
                for url in ctx_urls:
                    if isinstance(url, str) and url.strip():
                        mfr_url = url.strip()
                        break


    # 2. ProductTruth sources
    for source in product.sources:
        url = source.uri
        if not url:
            continue
        if not mfr_url:
            mfr_url = url
        elif url != mfr_url:
            candidate_urls.append(url)

    # 3. Document URLs from verified source context (if not already captured from packet)
    if source_ctx and getattr(source_ctx, "document_urls", None):
        for doc_url in source_ctx.document_urls:
            if doc_url and doc_url != mfr_url:
                candidate_urls.append(doc_url)


    # 4. Digital assets documents
    image_types = {
        AssetType.IMAGE,
        AssetType.PRIMARY_IMAGE,
        AssetType.ALTERNATE_IMAGE,
    }
    for asset in product.digital_assets:
        if asset.asset_type not in image_types and asset.uri and asset.uri != mfr_url:
            candidate_urls.append(asset.uri)

    # 5. Evidence sources as additional ref URLs
    for evidence in product.evidence:
        source_id = evidence.source_id
        src = next((s for s in product.sources if s.source_id == source_id), None)
        if src and src.uri and src.uri != mfr_url:
            candidate_urls.append(src.uri)

    # Deduplicate while preserving discovery order
    seen: set[str] = set()
    unique_candidates: list[str] = []
    for u in candidate_urls:
        u_clean = u.strip()
        if u_clean and u_clean.casefold() not in seen and u_clean != mfr_url:
            seen.add(u_clean.casefold())
            unique_candidates.append(u_clean)

    # Sort candidates by document type priority:
    # manual/install > spec/datasheet > tech doc/diagram > warranty > general doc
    ranked_urls = sorted(unique_candidates, key=_rank_document_url)

    return mfr_url, ranked_urls


def _build_attribute_triplets(
    product: ProductTruth,
) -> list[tuple[str | None, str | None, str | None]]:
    """Build a list of (label, value, uom) from enriched attributes.

    Attributes with no value are skipped. Sorted: verified/enriched first,
    then alphabetical by name.
    """
    results: list[tuple[str | None, str | None, str | None]] = []
    attrs_with_values = []
    for attr in product.attributes:
        val = _best_value(attr)
        if val is not None:
            uom = _best_uom(attr)
            attrs_with_values.append((attr.canonical_name, val, uom))
    for name, val, uom in attrs_with_values:
        results.append((name, val, uom))
    return results


def _best_value(attr: Any) -> str | None:
    """Return the best available value for an attribute record."""
    if attr.normalized_value is not None:
        return str(attr.normalized_value).strip() or None
    if attr.raw_value is not None:
        return str(attr.raw_value).strip() or None
    for candidate in attr.candidates:
        v = candidate.normalized_value or candidate.raw_value
        if v is not None:
            return str(v).strip() or None
    return None


def _best_uom(attr: Any) -> str | None:
    """Return the best available UOM for an attribute record."""
    if getattr(attr, "uom", None):
        return str(attr.uom).strip() or None
    for candidate in getattr(attr, "candidates", ()):
        if getattr(candidate, "uom", None):
            return str(candidate.uom).strip() or None
    return None


def _attr_value(attr_by_name: dict[str, Any], *keys: str) -> str | None:
    """Lookup an attribute by any of the given name keys (case-insensitive)."""
    for key in keys:
        attr = attr_by_name.get(key.casefold())
        if attr is not None:
            val = _best_value(attr)
            if val is not None:
                return val
    return None


def _find_attr(attr_by_name: dict[str, Any], *keys: str) -> Any | None:
    """Return the first attribute record matching any of the given keys."""
    for key in keys:
        attr = attr_by_name.get(key.casefold())
        if attr is not None:
            return attr
    return None


def _assign_doc(
    values: dict[str, Any],
    doc_assets: list[Any],
    col: str,
    keywords: tuple[str, ...],
) -> None:
    """Find the first document asset whose title matches any keyword and assign its URI."""
    if values.get(col):
        return  # already assigned
    for asset in doc_assets:
        title_lower = (asset.title or "").casefold()
        uri_lower = (asset.uri or "").casefold()
        type_lower = (
            asset.asset_type.value.casefold()
            if hasattr(asset.asset_type, "value")
            else str(asset.asset_type).casefold()
        )
        search_text = f"{title_lower} {uri_lower} {type_lower}"
        if any(kw in search_text for kw in keywords):
            values[col] = asset.uri
            return
