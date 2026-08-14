"""Deterministic structural validators that do not invent category-specific rules."""

from dataclasses import dataclass
from enum import StrEnum

from unilog_product_intelligence.data.normalize import PLACEHOLDER_VALUES
from unilog_product_intelligence.domain.truth import AttributeRecord, ProductTruth


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class DeterministicValidationIssue:
    code: str
    severity: ValidationSeverity
    message: str
    attribute_id: str | None = None


def validate_product_structure(product: ProductTruth) -> tuple[DeterministicValidationIssue, ...]:
    """Validate required/placeholder/duplicate-attribute invariants only."""

    issues: list[DeterministicValidationIssue] = []
    if not product.product_id:
        issues.append(
            DeterministicValidationIssue(
                "missing_product_id", ValidationSeverity.ERROR, "Product ID is required"
            )
        )
    if (
        product.identity.brand
        and product.identity.brand.raw_value in PLACEHOLDER_VALUES
        and product.identity.brand.normalized_value is not None
    ):
        issues.append(
            DeterministicValidationIssue(
                "placeholder_brand_not_null",
                ValidationSeverity.ERROR,
                "Brand placeholders must remain null canonically",
            )
        )
    seen: set[str] = set()
    for attribute in product.attributes:
        if attribute.attribute_id in seen:
            issues.append(
                DeterministicValidationIssue(
                    "duplicate_attribute",
                    ValidationSeverity.ERROR,
                    "Attribute identifier appears more than once",
                    attribute.attribute_id,
                )
            )
        seen.add(attribute.attribute_id)
    return tuple(issues)


def validate_attribute_structure(
    attribute: AttributeRecord,
) -> tuple[DeterministicValidationIssue, ...]:
    """Validate supported structural combinations without claiming LOV/UOM policy."""

    if attribute.status.value == "verified" and not attribute.evidence_ids:
        return (
            DeterministicValidationIssue(
                "verified_without_evidence",
                ValidationSeverity.ERROR,
                "Verified attributes require evidence",
                attribute.attribute_id,
            ),
        )
    return ()
