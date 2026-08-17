"""Deterministic category-aware attribute planning and reference-pack discovery."""

from __future__ import annotations

from unilog_product_intelligence.domain.truth import AttributeRecord, ProductTruth

from .models import (
    Applicability,
    AttributePlan,
    AttributeSchema,
    EnrichmentDecision,
    FinalAttributeStatus,
    ReferenceAvailability,
)
from .reference import (
    EXPECTED_REFERENCE_FILES,
    OFFICIAL_REFERENCE_MANIFEST,
    ReferencePack,
    ReferenceType,
)


class CategorySchemaRegistry:
    """Deterministic static category schema registry kept for backward compatibility."""

    _fitting = (
        AttributeSchema(attribute_id="fitting_type", canonical_name="Fitting Type", required=True),
        AttributeSchema(
            attribute_id="connection_type", canonical_name="Connection Type", required=True
        ),
        AttributeSchema(attribute_id="material", canonical_name="Material", required=True),
        AttributeSchema(
            attribute_id="size", canonical_name="Size", required=True, value_type="measurement"
        ),
    )
    _faucet = (
        AttributeSchema(attribute_id="faucet_type", canonical_name="Faucet Type", required=True),
        AttributeSchema(attribute_id="material", canonical_name="Material", required=False),
        AttributeSchema(attribute_id="finish", canonical_name="Finish", required=False),
        AttributeSchema(
            attribute_id="mounting_type", canonical_name="Mounting Type", required=False
        ),
    )

    def schemas_for(self, product: ProductTruth) -> tuple[AttributeSchema, ...]:
        haystack = " ".join(
            [
                *(product.classification.classpath or ()),
                product.classification.class_name or "",
                product.classification.fine or "",
                str(product.raw_value("Part_Desc") or ""),
            ]
        ).casefold()
        if "faucet" in haystack:
            return self._faucet
        if "fitting" in haystack or "coupling" in haystack or "adapter" in haystack:
            return self._fitting
        return ()


class AttributePlanner:
    """Plans category-supported, reference-grounded attribute work before any model call."""

    def __init__(
        self,
        reference_pack: ReferencePack | None = None,
        registry: CategorySchemaRegistry | None = None,
        max_planned_attributes: int = 50,
    ) -> None:
        self.reference_pack = reference_pack or ReferencePack(
            ReferenceAvailability.REFERENCE_UNAVAILABLE, {}
        )
        self.registry = registry or CategorySchemaRegistry()
        self.max_planned_attributes = max_planned_attributes

    def resolve_attribute_schema(
        self, product: ProductTruth
    ) -> tuple[tuple[AttributeSchema, ...], str, ReferenceAvailability]:
        """Resolve attribute schema following the strict 5-tier resolution hierarchy."""
        classpath = product.classification.classpath
        category = product.classification.class_name or product.classification.fine

        # Static schemas for fallback / core required attribute hints
        static_schema_map = {
            s.attribute_id: s for s in self.registry.schemas_for(product)
        }

        # 1. Try official reference pack (Category LOV or Global LOV)
        rules, source = self.reference_pack.resolve_category_rules(classpath, category)
        if rules:
            schemas: list[AttributeSchema] = []
            for rule in rules:
                canonical = rule.normalized_label or rule.attribute_label
                attr_id = (
                    canonical.strip()
                    .casefold()
                    .replace(" ", "_")
                    .replace("/", "_")
                    .replace("-", "_")
                )
                rem_low = (rule.remarks or "").casefold()
                guide_low = (rule.guidelines or "").casefold()
                static_match = static_schema_map.get(attr_id)
                is_req = (
                    "required" in rem_low
                    or "required" in guide_low
                    or (static_match.required if static_match else False)
                )
                schemas.append(
                    AttributeSchema(
                        attribute_id=attr_id,
                        canonical_name=canonical,
                        required=is_req,
                        filtering=rule.filtering,
                        allowed_values=rule.attribute_values,
                        allowed_uom=rule.allowed_uom,
                        reference_availability=ReferenceAvailability.REFERENCE_AVAILABLE,
                        classpaths=rule.classpath or (),
                        leaf_node=rule.leaf_node,
                        schema_source=source,
                        reason=f"official reference rule from {source}",
                    )
                )
            return tuple(schemas), source, ReferenceAvailability.REFERENCE_AVAILABLE

        # 2. Check static schema registry (backward compatibility for Faucets/Fittings)
        registry_schemas = self.registry.schemas_for(product)
        if registry_schemas:
            return (
                registry_schemas,
                "CATEGORY_SCHEMA_REGISTRY",
                self.reference_pack.availability,
            )

        # 3. Fallback to existing ProductTruth attributes
        if product.attributes:
            fallback_schemas = tuple(
                AttributeSchema(
                    attribute_id=item.attribute_id,
                    canonical_name=item.canonical_name,
                    required=False,
                    reference_availability=ReferenceAvailability.REFERENCE_UNAVAILABLE,
                    schema_source="FALLBACK_EXISTING_ATTRIBUTES",
                    reason="existing ProductTruth attribute; category schema unavailable",
                )
                for item in product.attributes
            )
            return (
                fallback_schemas,
                "FALLBACK_EXISTING_ATTRIBUTES",
                ReferenceAvailability.REFERENCE_UNAVAILABLE,
            )

        return (), "FALLBACK_EXISTING_ATTRIBUTES", ReferenceAvailability.REFERENCE_UNAVAILABLE

    def plan(self, product: ProductTruth) -> tuple[AttributePlan, ...]:
        schemas, schema_source, ref_avail = self.resolve_attribute_schema(product)
        if not schemas:
            return ()

        existing = {item.attribute_id: item for item in product.attributes}
        plans: list[AttributePlan] = []

        for schema in schemas:
            current = existing.get(schema.attribute_id)
            current_status = _status(current)
            current_value = current.normalized_value if current else None
            evidence_available = bool(
                current
                and (
                    current.evidence_ids
                    or any(c.evidence_ids for c in current.candidates)
                )
            )

            ref_values = self.reference_pack.get_allowed_values(
                schema.canonical_name,
                classpath=product.classification.classpath,
                category=product.classification.class_name,
            )
            values = ref_values if ref_values else schema.allowed_values

            ref_uoms = self.reference_pack.get_allowed_uom(
                schema.canonical_name,
                classpath=product.classification.classpath,
                category=product.classification.class_name,
            )
            uoms = ref_uoms if ref_uoms else schema.allowed_uom

            has_ref = bool(
                values
                or uoms
                or ref_avail == ReferenceAvailability.REFERENCE_AVAILABLE
            )
            plan_ref_avail = (
                ReferenceAvailability.REFERENCE_AVAILABLE
                if has_ref
                else ReferenceAvailability.REFERENCE_UNAVAILABLE
            )

            # Priority calculation: REQUIRED > FILTERING > OPTIONAL
            if schema.required:
                priority = 90
            elif schema.filtering is True:
                priority = 70
            else:
                priority = 50

            if (
                current
                and current_status in {
                    FinalAttributeStatus.VERIFIED,
                    FinalAttributeStatus.NORMALIZED,
                    FinalAttributeStatus.ENRICHED,
                }
                and evidence_available
            ):
                decision = EnrichmentDecision.NO_ACTION
                reason = "Existing publishable value is not re-enriched."
            elif evidence_available:
                decision = EnrichmentDecision.VERIFY_EXISTING
                reason = "Existing value has evidence and requires deterministic verification."
            elif schema.required:
                decision = EnrichmentDecision.ENRICH
                reason = "Required category attribute is missing and must be evidence-backed."
            else:
                decision = EnrichmentDecision.ENRICH
                reason = "Optional category attribute may be enriched only when evidence exists."

            plans.append(
                AttributePlan(
                    product_id=product.product_id,
                    category=product.classification.class_name,
                    classpath=product.classification.classpath,
                    leaf_node=schema.leaf_node or product.classification.class_name,
                    attribute_id=schema.attribute_id,
                    attribute_name=schema.canonical_name,
                    applicability=Applicability.REQUIRED
                    if schema.required
                    else Applicability.OPTIONAL,
                    required=schema.required,
                    filtering=schema.filtering,
                    current_status=current_status,
                    current_value=current_value,
                    evidence_available=evidence_available,
                    enrichment_required=decision,
                    validation_requirements=("evidence", "format", "uom")
                    + (("lov",) if values else ()),
                    allowed_values=values,
                    allowed_uom=uoms,
                    reference_availability=plan_ref_avail,
                    schema_source=schema.schema_source or schema_source,
                    priority=priority,
                    reason=reason,
                )
            )

        # Deterministic sorting: priority descending, then attribute_id
        sorted_plans = sorted(plans, key=lambda item: (-item.priority, item.attribute_id))

        # Bound plan size while strictly preserving all required attributes
        if len(sorted_plans) > self.max_planned_attributes:
            required_plans = [
                p for p in sorted_plans if p.applicability == Applicability.REQUIRED
            ]
            other_plans = [
                p for p in sorted_plans if p.applicability != Applicability.REQUIRED
            ]
            remaining_slots = max(0, self.max_planned_attributes - len(required_plans))
            keep_others = other_plans[:remaining_slots]
            sorted_plans = sorted(
                required_plans + keep_others,
                key=lambda item: (-item.priority, item.attribute_id),
            )

        return tuple(sorted_plans)


def _status(attribute: AttributeRecord | None) -> FinalAttributeStatus:
    if attribute is None or attribute.normalized_value is None:
        return FinalAttributeStatus.MISSING
    mapping = {
        "verified": FinalAttributeStatus.VERIFIED,
        "normalized": FinalAttributeStatus.NORMALIZED,
        "enriched": FinalAttributeStatus.ENRICHED,
        "inferred": FinalAttributeStatus.INFERRED,
        "conflicted": FinalAttributeStatus.CONFLICTED,
        "rejected": FinalAttributeStatus.REJECTED,
    }
    return mapping.get(attribute.status.value, FinalAttributeStatus.REVIEW_REQUIRED)


__all__ = [
    "AttributePlanner",
    "CategorySchemaRegistry",
    "EXPECTED_REFERENCE_FILES",
    "OFFICIAL_REFERENCE_MANIFEST",
    "ReferencePack",
    "ReferenceType",
]
