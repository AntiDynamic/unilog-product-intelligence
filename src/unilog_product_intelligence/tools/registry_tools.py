"""Typed, bounded deterministic application capabilities."""

from typing import Any

from pydantic import BaseModel, ConfigDict

from unilog_product_intelligence.deterministic.registry import (
    BrandRegistry,
    FractionRegistry,
    LOVRegistry,
    ManufacturerRegistry,
    ResolutionResult,
    TaxonomyRegistry,
    UOMRegistry,
)
from unilog_product_intelligence.deterministic.validation import validate_attribute_structure
from unilog_product_intelligence.domain.truth import AttributeRecord


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    value: Any = None
    reason: str | None = None


class AttributeValidationArgs(BaseModel):
    attribute: AttributeRecord


class ApplicationTools:
    """Only exposes registry lookups and structural validation already owned by the application."""

    def __init__(
        self,
        manufacturers: ManufacturerRegistry | None = None,
        brands: BrandRegistry | None = None,
        taxonomy: TaxonomyRegistry | None = None,
        lov: LOVRegistry | None = None,
        uom: UOMRegistry | None = None,
        fractions: FractionRegistry | None = None,
    ) -> None:
        self.manufacturers = manufacturers or ManufacturerRegistry()
        self.brands = brands or BrandRegistry()
        self.taxonomy = taxonomy or TaxonomyRegistry()
        self.lov = lov or LOVRegistry()
        self.uom = uom or UOMRegistry()
        self.fractions = fractions or FractionRegistry()

    def resolve_manufacturer(self, raw_value: str | None) -> ToolResult:
        return _resolution(self.manufacturers.resolve(raw_value))

    def resolve_brand(
        self, raw_value: str | None, manufacturer_id: str | None = None
    ) -> ToolResult:
        return _resolution(self.brands.resolve_for_manufacturer(raw_value, manufacturer_id))

    def get_taxonomy_context(self, query: str | None = None) -> ToolResult:
        return _context(self.taxonomy, query)

    def get_category_schema(self, category_id: str) -> ToolResult:
        return _context(self.lov, category_id)

    def get_allowed_values(self, attribute: str, category_id: str | None = None) -> ToolResult:
        return _context(self.lov, f"{category_id}:{attribute}" if category_id else attribute)

    def normalize_uom(self, raw_value: str | None) -> ToolResult:
        return _resolution(self.uom.resolve(raw_value))

    def get_fraction_mapping(self, raw_value: str | None) -> ToolResult:
        return _resolution(self.fractions.resolve(raw_value))

    def validate_attribute(self, args: AttributeValidationArgs) -> ToolResult:
        issues = validate_attribute_structure(args.attribute)
        return ToolResult(
            status="valid" if not issues else "invalid", value=[issue.__dict__ for issue in issues]
        )


def _resolution(result: ResolutionResult) -> ToolResult:
    if result.canonical_record is not None:
        return ToolResult(status=result.status.value, value=result.canonical_record.__dict__)
    return ToolResult(
        status=result.status.value,
        value=[candidate.record.__dict__ for candidate in result.candidates],
        reason=result.reason,
    )


def _context(registry: Any, query: str | None) -> ToolResult:
    if not registry.available:
        return ToolResult(status="reference_data_unavailable", reason="registry_not_loaded")
    result = registry.resolve(query)
    return _resolution(result)
