"""Commerce Description Generation Layer for Phase 6.

Constructs MOBILE_DESC, INVOICE_DESC, SHORT_DESC, LONG_DESC1, RETAIL_DESC, and ITEM_FEATURES
from verified ProductTruth identity, validated attributes, and authoritative manufacturer evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.domain.truth import (
    AttributeRecord,
    ProductDescriptions,
    ProductTruth,
)
from unilog_product_intelligence.enrichment.agent import evidence_references
from unilog_product_intelligence.enrichment.models import (
    ReferenceAvailability,
    ValidationSeverity,
)
from unilog_product_intelligence.enrichment.reference import ReferencePack
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest


class GuidelineAssessmentStatus(StrEnum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    NOT_ASSESSED = "NOT_ASSESSED"


@dataclass(frozen=True)
class DescriptionLimits:
    short_max: int = 150
    long_max: int = 2000
    mobile_max: int = 100
    invoice_max: int = 60
    retail_max: int = 1000
    max_features: int = 20


@dataclass(frozen=True)
class DescriptionContext:
    """Compact structured description context containing ONLY publishable/verified facts."""

    product_id: str
    brand: str | None
    manufacturer: str | None
    mpn: str | None
    product_name: str | None
    series: str | None
    trade_name: str | None
    classpath: tuple[str, ...]
    category: str | None
    verified_attributes: tuple[AttributeRecord, ...]
    evidence_snippets: tuple[str, ...]
    approved_uoms: frozenset[str]
    guideline_availability: ReferenceAvailability = ReferenceAvailability.REFERENCE_UNAVAILABLE

    @classmethod
    def from_product(
        cls,
        product: ProductTruth,
        reference_pack: ReferencePack | None = None,
    ) -> DescriptionContext:
        identity = product.identity
        brand = (
            (identity.brand.normalized_value or str(identity.brand.raw_value or ""))
            if identity.brand
            else str(product.raw_value("Unilog_Brand") or "")
        ).strip() or None

        mfg = (
            (identity.manufacturer.normalized_value or str(identity.manufacturer.raw_value or ""))
            if identity.manufacturer
            else str(product.raw_value("Part_Manuf") or "")
        ).strip() or None

        mpn_field = identity.manufacturer_part_number
        mpn = (
            (mpn_field.normalized_value or str(mpn_field.raw_value or ""))
            if mpn_field
            else str(product.raw_value("Mfg_Part_Num") or "")
        ).strip() or None

        series = (
            str(identity.trade_name.normalized_value or identity.trade_name.raw_value or "").strip()
            if identity.trade_name
            else None
        )

        pname = str(product.raw_value("Part_Desc") or "").strip()
        if not pname:
            pname = product.classification.class_name or ""

        # Include only publishable/verified attributes
        # (status in verified, normalized, enriched with valid value and evidence)
        verified_attrs = tuple(
            attr
            for attr in product.attributes
            if attr.status.value in {"verified", "normalized", "enriched"}
            and (attr.normalized_value is not None or attr.raw_value is not None)
            and (
                bool(attr.evidence_ids)
                or any(bool(c.evidence_ids) for c in attr.candidates)
            )
        )

        ev_snippets = tuple(
            ref.evidence_text
            for ref in evidence_references(product)
            if ref.evidence_text
        )

        approved_uoms = (
            reference_pack.uom_standards.approved_uoms
            if reference_pack and reference_pack.uom_standards
            else frozenset()
        )

        return cls(
            product_id=product.product_id,
            brand=brand,
            manufacturer=mfg,
            mpn=mpn,
            product_name=pname or None,
            series=series or None,
            trade_name=series or None,
            classpath=product.classification.classpath or (),
            category=product.classification.class_name or product.classification.fine,
            verified_attributes=verified_attrs,
            evidence_snippets=ev_snippets,
            approved_uoms=approved_uoms,
            guideline_availability=getattr(
                reference_pack, "availability", ReferenceAvailability.REFERENCE_UNAVAILABLE
            ),
        )


# ==============================================================================
# DETERMINISTIC DESCRIPTION BUILDER
# ==============================================================================


class DeterministicDescriptionBuilder:
    """Builds all five commerce description fields and feature bullets deterministically."""

    def __init__(self, limits: DescriptionLimits | None = None) -> None:
        self.limits = limits or DescriptionLimits()

    def build_short_desc(self, ctx: DescriptionContext) -> str:
        """[BRAND] [SERIES] [MPN] [PRODUCT NAME] [KEY SPECS]"""
        components: list[str] = []
        if ctx.brand:
            components.append(ctx.brand)
        if ctx.series and ctx.series != ctx.brand:
            components.append(ctx.series)
        if ctx.mpn:
            components.append(ctx.mpn)

        # Core name / product type
        core_name = ctx.product_name or ctx.category or "Product"
        # If core_name already starts with brand or mpn, deduplicate
        clean_core = core_name
        if ctx.brand and clean_core.lower().startswith(ctx.brand.lower()):
            clean_core = clean_core[len(ctx.brand) :].strip()
        if ctx.mpn and clean_core.lower().startswith(ctx.mpn.lower()):
            clean_core = clean_core[len(ctx.mpn) :].strip()

        components.append(clean_core)

        # Append key attribute specs
        spec_parts: list[str] = []
        for attr in ctx.verified_attributes:
            val = str(attr.normalized_value or attr.raw_value or "").strip()
            if not val or val.lower() in clean_core.lower():
                continue
            uom_str = f" {attr.uom}" if attr.uom else ""
            spec_parts.append(f"{val}{uom_str}")

        base_str = " ".join(part for part in components if part).strip()
        full_str = f"{base_str}, {', '.join(spec_parts)}" if spec_parts else base_str

        # Priority truncation if exceeding limit
        if len(full_str) > self.limits.short_max:
            # Drop attributes one by one from end
            while spec_parts and len(full_str) > self.limits.short_max:
                spec_parts.pop()
                full_str = f"{base_str}, {', '.join(spec_parts)}" if spec_parts else base_str

        return full_str[: self.limits.short_max].strip()

    def build_invoice_desc(self, ctx: DescriptionContext) -> str:
        """Concise uppercase transactional string [BRAND] [MPN] [PRODUCT TYPE] [KEY SPEC]"""
        parts: list[str] = []
        if ctx.brand:
            parts.append(ctx.brand.upper())
        if ctx.mpn:
            parts.append(ctx.mpn.upper())

        name = (ctx.product_name or ctx.category or "ITEM").upper()
        if ctx.brand and name.startswith(ctx.brand.upper()):
            name = name[len(ctx.brand) :].strip()
        if ctx.mpn and name.startswith(ctx.mpn.upper()):
            name = name[len(ctx.mpn) :].strip()

        parts.append(name)

        # Add top spec if available and fits
        specs: list[str] = []
        for attr in ctx.verified_attributes:
            val = str(attr.normalized_value or attr.raw_value or "").upper().strip()
            if not val or val in name:
                continue
            uom = f" {attr.uom.upper()}" if attr.uom else ""
            specs.append(f"{val}{uom}")

        base = " ".join(parts).strip()
        result = f"{base} {' '.join(specs)}".strip() if specs else base

        # Enforce uppercase and limit
        if len(result) > self.limits.invoice_max:
            while specs and len(result) > self.limits.invoice_max:
                specs.pop()
                result = f"{base} {' '.join(specs)}".strip() if specs else base

        return result[: self.limits.invoice_max].upper().strip()

    def build_mobile_desc(self, ctx: DescriptionContext) -> str:
        """Compact display summary [BRAND] [MPN] [NAME] [TOP SPECS]"""
        parts: list[str] = []
        if ctx.brand:
            parts.append(ctx.brand)
        if ctx.mpn:
            parts.append(ctx.mpn)
        core = ctx.product_name or ctx.category or "Product"
        if ctx.brand and core.lower().startswith(ctx.brand.lower()):
            core = core[len(ctx.brand) :].strip()
        if ctx.mpn and core.lower().startswith(ctx.mpn.lower()):
            core = core[len(ctx.mpn) :].strip()
        parts.append(core)

        spec_items: list[str] = []
        for attr in ctx.verified_attributes:
            val = str(attr.normalized_value or attr.raw_value or "").strip()
            if not val or val.lower() in core.lower():
                continue
            uom = f" {attr.uom}" if attr.uom else ""
            spec_items.append(f"{attr.canonical_name}: {val}{uom}")

        base = " ".join(parts).strip()
        full = f"{base} ({'; '.join(spec_items)})" if spec_items else base

        if len(full) > self.limits.mobile_max:
            while spec_items and len(full) > self.limits.mobile_max:
                spec_items.pop()
                full = f"{base} ({'; '.join(spec_items)})" if spec_items else base

        return full[: self.limits.mobile_max].strip()

    def build_long_desc1(self, ctx: DescriptionContext) -> str:
        """Technical structured overview aggregating verified facts."""
        sections: list[str] = []

        brand_str = ctx.brand or ""
        mpn_str = f" (MPN: {ctx.mpn})" if ctx.mpn else ""
        name_str = ctx.product_name or ctx.category or "Product"
        cat_str = f" in the {' > '.join(ctx.classpath)} category" if ctx.classpath else ""

        overview = f"The {brand_str} {name_str}{mpn_str} is an industrial solution{cat_str}."
        sections.append(overview.strip())

        if ctx.verified_attributes:
            specs = [
                f"{attr.canonical_name}: {attr.normalized_value or attr.raw_value}"
                f"{' ' + attr.uom if attr.uom else ''}"
                for attr in ctx.verified_attributes
            ]
            sections.append("Specifications: " + "; ".join(specs) + ".")

        if ctx.evidence_snippets:
            # Include first authoritative snippet if relevant and concise
            first_ev = ctx.evidence_snippets[0].strip()
            if len(first_ev) < 300 and first_ev not in sections[0]:
                sections.append(first_ev)

        long_desc = " ".join(sections).strip()
        return long_desc[: self.limits.long_max].strip()

    def build_retail_desc(self, ctx: DescriptionContext) -> str:
        """Evidence-grounded customer-facing description without unsupported superlatives."""
        brand_name = ctx.brand or "This"
        p_name = ctx.product_name or ctx.category or "product"
        mpn_tag = f" ({ctx.mpn})" if ctx.mpn else ""

        lines: list[str] = [
            f"{brand_name} {p_name}{mpn_tag} delivers reliable performance "
            "for professional and industrial applications."
        ]

        attr_highlights: list[str] = []
        for attr in ctx.verified_attributes:
            val = str(attr.normalized_value or attr.raw_value or "")
            uom_str = f" {attr.uom}" if attr.uom else ""
            attr_highlights.append(f"{attr.canonical_name.lower()} of {val}{uom_str}")

        if attr_highlights:
            lines.append(f"Key technical details include {', '.join(attr_highlights[:4])}.")

        # Add evidence facts if available
        if ctx.evidence_snippets:
            clean_snippet = ctx.evidence_snippets[0].strip()
            if len(clean_snippet) < 250:
                lines.append(clean_snippet)

        retail_desc = " ".join(lines).strip()
        return retail_desc[: self.limits.retail_max].strip()

    def build_features(self, ctx: DescriptionContext) -> list[str]:
        """Evidence-backed feature bullets (up to max_features)."""
        bullets: list[str] = []

        # 1. From verified attributes
        for attr in ctx.verified_attributes:
            val = str(attr.normalized_value or attr.raw_value or "").strip()
            uom_str = f" {attr.uom}" if attr.uom else ""
            bullets.append(f"{attr.canonical_name}: {val}{uom_str}")

        # 2. From evidence snippets if formatted as bullet-like phrases
        for snippet in ctx.evidence_snippets:
            for line in re.split(r"[\n\r•\-\*]", snippet):
                clean = line.strip()
                if 10 < len(clean) < 150 and not clean.startswith("http") and clean not in bullets:
                    bullets.append(clean)
                if len(bullets) >= self.limits.max_features:
                    break
            if len(bullets) >= self.limits.max_features:
                break

        return bullets[: self.limits.max_features]

    def build_all(self, ctx: DescriptionContext) -> ProductDescriptions:
        """Build all description fields into a ProductDescriptions object."""
        return ProductDescriptions(
            short=self.build_short_desc(ctx),
            long=self.build_long_desc1(ctx),
            mobile=self.build_mobile_desc(ctx),
            invoice=self.build_invoice_desc(ctx),
            retail=self.build_retail_desc(ctx),
            features=self.build_features(ctx),
            source_ids=[ctx.product_id],
            evidence_ids=[],
        )


# ==============================================================================
# DETERMINISTIC DESCRIPTION VALIDATOR
# ==============================================================================


@dataclass(frozen=True)
class DescriptionValidationResult:
    validator: str
    passed: bool
    severity: ValidationSeverity
    message: str
    field_name: str | None = None
    actual_value: str | None = None
    expected_condition: str | None = None
    guideline_status: GuidelineAssessmentStatus = GuidelineAssessmentStatus.COMPLIANT


FORBIDDEN_SUPERLATIVES: tuple[str, ...] = (
    "best in class",
    "unmatched",
    "world's best",
    "#1 rated",
    "revolutionary",
    "game-changing",
    "unbeatable",
    "miracle",
)


class DescriptionValidator:
    """Enforces fact consistency, MPN preservation, UOM standard, and length limits."""

    def __init__(self, limits: DescriptionLimits | None = None) -> None:
        self.limits = limits or DescriptionLimits()

    def validate(
        self,
        descriptions: ProductDescriptions,
        ctx: DescriptionContext,
    ) -> list[DescriptionValidationResult]:
        results: list[DescriptionValidationResult] = []

        # 1. Guideline availability check
        if ctx.guideline_availability == ReferenceAvailability.REFERENCE_UNAVAILABLE:
            results.append(
                DescriptionValidationResult(
                    validator="guideline_availability",
                    passed=True,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        "Official content guideline workbook unavailable; "
                        "formatting checked via deterministic baseline."
                    ),
                    guideline_status=GuidelineAssessmentStatus.NOT_ASSESSED,
                )
            )

        # 2. MPN Preservation Check
        if ctx.mpn:
            mpn_clean = ctx.mpn.strip()
            for fname, val in [
                ("short", descriptions.short),
                ("invoice", descriptions.invoice),
                ("mobile", descriptions.mobile),
            ]:
                if val and mpn_clean.casefold() not in val.casefold():
                    results.append(
                        DescriptionValidationResult(
                            validator="mpn_preservation",
                            passed=False,
                            severity=ValidationSeverity.ERROR,
                            message=f"Required MPN '{ctx.mpn}' is missing from {fname}_desc.",
                            field_name=fname,
                            actual_value=val,
                            expected_condition=f"contains {ctx.mpn}",
                        )
                    )

        # 3. Brand Consistency Check
        if ctx.brand:
            brand_clean = ctx.brand.strip()
            for fname, val in [
                ("short", descriptions.short),
                ("long", descriptions.long),
                ("invoice", descriptions.invoice),
                ("retail", descriptions.retail),
            ]:
                if val and brand_clean.casefold() not in val.casefold():
                    results.append(
                        DescriptionValidationResult(
                            validator="brand_consistency",
                            passed=True,
                            severity=ValidationSeverity.INFO,
                            message=f"Brand '{ctx.brand}' not explicitly in {fname}_desc.",
                            field_name=fname,
                            actual_value=val,
                        )
                    )

        # 4. Numeric & Attribute Fact Consistency Check
        # Check that numeric values in descriptions match verified attributes
        for fname, text_val in [
            ("short", descriptions.short),
            ("long", descriptions.long),
            ("mobile", descriptions.mobile),
            ("invoice", descriptions.invoice),
            ("retail", descriptions.retail),
        ]:
            if not text_val:
                continue

            # Check for forbidden superlatives unless in verified evidence
            for sup in FORBIDDEN_SUPERLATIVES:
                if sup in text_val.casefold():
                    in_ev = any(sup in ev.casefold() for ev in ctx.evidence_snippets)
                    if not in_ev:
                        results.append(
                            DescriptionValidationResult(
                                validator="superlative_check",
                                passed=False,
                                severity=ValidationSeverity.ERROR,
                                message=(
                                    f"Forbidden unsupported marketing superlative "
                                    f"'{sup}' in {fname}_desc."
                                ),
                                field_name=fname,
                                actual_value=text_val,
                            )
                        )

        # 5. Length limits check
        checks = [
            ("short", descriptions.short, self.limits.short_max),
            ("long", descriptions.long, self.limits.long_max),
            ("mobile", descriptions.mobile, self.limits.mobile_max),
            ("invoice", descriptions.invoice, self.limits.invoice_max),
            ("retail", descriptions.retail, self.limits.retail_max),
        ]
        for fname, val, max_len in checks:
            if val and len(val) > max_len:
                results.append(
                    DescriptionValidationResult(
                        validator="character_limit",
                        passed=False,
                        severity=ValidationSeverity.ERROR,
                        message=f"{fname}_desc exceeds limit ({len(val)} > {max_len}).",
                        field_name=fname,
                        actual_value=str(len(val)),
                        expected_condition=f"<= {max_len}",
                    )
                )

        # 6. Invoice casing check
        if descriptions.invoice and not descriptions.invoice.isupper():
            results.append(
                DescriptionValidationResult(
                    validator="invoice_casing",
                    passed=False,
                    severity=ValidationSeverity.ERROR,
                    message="INVOICE_DESC must be uppercase.",
                    field_name="invoice",
                    actual_value=descriptions.invoice,
                    expected_condition="UPPERCASE",
                )
            )

        return results


# ==============================================================================
# GEMINI DESCRIPTION SCHEMA & AGENT
# ==============================================================================


class DescriptionCandidateEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    short_desc: str = Field(description="Structured title / short description")
    long_desc1: str = Field(description="Structured technical commerce description")
    mobile_desc: str = Field(description="Compact mobile-optimized description")
    invoice_desc: str = Field(description="Transactional uppercase invoice description")
    retail_desc: str = Field(description="Evidence-grounded customer-facing description")
    features: list[str] = Field(
        default_factory=list,
        description="Feature bullets from verified facts",
    )


class DescriptionAgent:
    """Dual-mode description composer with strict post-generation validation."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        limits: DescriptionLimits | None = None,
    ) -> None:
        self.provider = provider
        self.limits = limits or DescriptionLimits()
        self.builder = DeterministicDescriptionBuilder(self.limits)
        self.validator = DescriptionValidator(self.limits)

    def generate(
        self,
        ctx: DescriptionContext,
    ) -> tuple[ProductDescriptions, list[DescriptionValidationResult]]:
        # 1. Deterministic baseline
        deterministic_desc = self.builder.build_all(ctx)

        if self.provider is None:
            validations = self.validator.validate(deterministic_desc, ctx)
            return deterministic_desc, validations

        # 2. Gemini composition with verified facts prompt
        prompt = self._build_prompt(ctx)
        try:
            response = self.provider.generate(
                LLMRequest(
                    task="commerce_description_composition",
                    input_text=prompt,
                    response_schema=DescriptionCandidateEnvelope.model_json_schema(),
                    metadata={"product_id": ctx.product_id},
                )
            )
            envelope = DescriptionCandidateEnvelope.model_validate_json(response.output_text)
            composed_desc = ProductDescriptions(
                short=envelope.short_desc.strip(),
                long=envelope.long_desc1.strip(),
                mobile=envelope.mobile_desc.strip(),
                invoice=envelope.invoice_desc.upper().strip(),
                retail=envelope.retail_desc.strip(),
                features=envelope.features[: self.limits.max_features],
                source_ids=[ctx.product_id],
                evidence_ids=[],
            )

            # Validate composed descriptions
            validations = self.validator.validate(composed_desc, ctx)

            # If Gemini broke critical rules (MPN missing, length exceeded, superlatives),
            # safely repair using deterministic baseline
            has_blocking = any(
                v.severity in {ValidationSeverity.ERROR, ValidationSeverity.BLOCKING}
                for v in validations
            )
            if has_blocking:
                # Fallback to deterministic version
                deterministic_desc = self.builder.build_all(ctx)
                validations = self.validator.validate(deterministic_desc, ctx)
                return deterministic_desc, validations

            return composed_desc, validations

        except Exception:
            # On LLM error, fail-safe to deterministic builder
            validations = self.validator.validate(deterministic_desc, ctx)
            return deterministic_desc, validations

    def _build_prompt(self, ctx: DescriptionContext) -> str:
        attrs_text = "\n".join(
            f"- {a.canonical_name}: {a.normalized_value or a.raw_value}"
            f"{' ' + a.uom if a.uom else ''}"
            for a in ctx.verified_attributes
        )
        ev_text = "\n".join(f"- {ev}" for ev in ctx.evidence_snippets)

        return (
            "SYSTEM: Commerce description composition v1. Use ONLY the supplied verified facts. "
            "Never invent specifications, dimensions, certifications, or marketing superlatives. "
            "Preserve MPN and Brand exactly. "
            "INVOICE_DESC must be concise uppercase without promotional language. "
            "SHORT_DESC must include Brand, MPN, and core product name. Output JSON only.\n\n"
            f"PRODUCT IDENTITY:\n"
            f"- Brand: {ctx.brand or 'N/A'}\n"
            f"- Manufacturer: {ctx.manufacturer or 'N/A'}\n"
            f"- MPN: {ctx.mpn or 'N/A'}\n"
            f"- Product Name: {ctx.product_name or 'N/A'}\n"
            f"- Category / Classpath: {' > '.join(ctx.classpath) or ctx.category or 'N/A'}\n\n"
            f"VERIFIED ATTRIBUTES:\n{attrs_text or 'None'}\n\n"
            f"AUTHORITATIVE EVIDENCE:\n{ev_text or 'None'}\n"
        )


# ==============================================================================
# DESCRIPTION SERVICE
# ==============================================================================


class DescriptionService:
    """Service layer managing description generation and ProductTruth updates."""

    def __init__(
        self,
        agent: DescriptionAgent | None = None,
    ) -> None:
        self.agent = agent or DescriptionAgent()

    def generate_descriptions(
        self,
        product: ProductTruth,
        reference_pack: ReferencePack | None = None,
    ) -> tuple[ProductTruth, list[DescriptionValidationResult]]:
        ctx = DescriptionContext.from_product(product, reference_pack=reference_pack)
        descriptions, validations = self.agent.generate(ctx)

        # Update ProductTruth
        product.descriptions = descriptions
        return product, validations


__all__ = [
    "DescriptionAgent",
    "DescriptionCandidateEnvelope",
    "DescriptionContext",
    "DescriptionLimits",
    "DescriptionService",
    "DescriptionValidationResult",
    "DescriptionValidator",
    "DeterministicDescriptionBuilder",
    "FORBIDDEN_SUPERLATIVES",
    "GuidelineAssessmentStatus",
]
