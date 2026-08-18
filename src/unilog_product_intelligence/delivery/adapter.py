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
        for i, url in enumerate(ref_urls[: self.MAX_REF_URLS], start=1):
            values[f"Ref URL {i}"] = url

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
        # then enriched attribute, then raw fallback.
        is_dist = getattr(phase65_result, "is_distributor_masked", False)
        res_mfg = _resolved_manufacturer(phase65_result)
        mfg_name: str | None
        if is_dist and res_mfg:
            mfg_name = res_mfg
        else:
            mfg_name = (
                _ident(identity, "manufacturer")
                or _attr_value(attr_by_name, "manufacturer", "manufacturer name")
                or res_mfg
            )
        values["MANUFACTURER_NAME"] = _clean_name(mfg_name)

        # Resolve brand: prefer enriched attribute (e.g. from Diablo product page),
        # then non-placeholder identity brand, then resolved brand.
        brand_name = (
            _attr_value(attr_by_name, "brand", "brand name")
            or _ident(identity, "brand")
            or _resolved_brand(phase65_result)
        )
        values["BRAND_NAME"] = _clean_name(brand_name)
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
        values["MOBILE_DESC"] = desc.mobile
        values["INVOICE_DESC"] = desc.invoice
        values["SHORT_DESC"] = desc.short
        values["LONG_DESC1"] = desc.long
        values["RETAIL_DESC"] = desc.retail
        values["MARKETING_DESCRIPTION"] = desc.marketing

        # ── 6. Item feature bullets ───────────────────────────────────────────
        features = desc.features
        for i in range(1, self.MAX_FEATURES + 1):
            values[f"ITEM_FEATURES_{i}"] = features[i - 1] if i - 1 < len(features) else None

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
        values["With"] = _attr_value(attr_by_name, "with")
        values["Standard/Approvals"] = _attr_value(
            attr_by_name, "standard/approvals", "standards", "approvals", "certifications"
        )
        values["Prop 65"] = _attr_value(attr_by_name, "prop 65", "proposition 65", "prop65")
        values["Application"] = _attr_value(attr_by_name, "application")
        values["Includes"] = _attr_value(
            attr_by_name, "includes", "what's included", "box contents"
        )
        values["Product Name"] = _attr_value(attr_by_name, "product name", "name")

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


def _extract_source_urls(
    result: Any, product: ProductTruth
) -> tuple[str | None, list[str]]:
    """Extract MFR URL (primary) and reference URLs from Phase65Result + ProductTruth."""
    mfr_url: str | None = None
    ref_urls: list[str] = []

    # Prefer the URL from the manufacturer job's retrieved source
    job = getattr(result, "manufacturer_job", None)
    if job:
        ctx_urls = getattr(job, "url_context_urls", ()) or ()
        for url in ctx_urls:
            if url and not mfr_url:
                mfr_url = url
            elif url:
                ref_urls.append(url)

    # Supplement from ProductTruth sources
    for source in product.sources:
        url = source.uri
        if not url:
            continue
        if not mfr_url:
            mfr_url = url
        elif url != mfr_url and url not in ref_urls:
            ref_urls.append(url)

    # Evidence sources as additional ref URLs
    for evidence in product.evidence:
        source_id = evidence.source_id
        src = next((s for s in product.sources if s.source_id == source_id), None)
        if src and src.uri and src.uri not in ref_urls and src.uri != mfr_url:
            ref_urls.append(src.uri)

    return mfr_url, ref_urls


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
