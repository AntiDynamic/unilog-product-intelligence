"""Deterministic Phase 6 validation and publication decisions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from unilog_product_intelligence.domain.truth import (
    ProductTruth,
    SourceAuthority,
    SourceStatus,
    SourceType,
)

from .models import (
    AttributePlan,
    EnrichmentCandidate,
    FinalAttributeStatus,
    PublicationState,
    ReviewPayload,
    ValidationResult,
    ValidationSeverity,
)


class ValidationPipeline:
    """Every validator emits a structured result; callers decide publication state."""

    def validate(
        self,
        product: ProductTruth,
        plans: Iterable[AttributePlan],
        candidates: Iterable[EnrichmentCandidate],
    ) -> tuple[
        tuple[EnrichmentCandidate, ...], tuple[ValidationResult, ...], tuple[ReviewPayload, ...]
    ]:
        plan_by_id = {plan.attribute_id: plan for plan in plans}
        candidate_items = tuple(candidates)
        results: list[ValidationResult] = []
        updated: list[EnrichmentCandidate] = []
        for candidate in candidate_items:
            plan = plan_by_id.get(candidate.attribute_id)
            candidate_results = self._validate_one(product, plan, candidate)
            results.extend(candidate_results)
            blocking = any(
                item.severity == ValidationSeverity.BLOCKING for item in candidate_results
            )
            error = any(item.severity == ValidationSeverity.ERROR for item in candidate_results)
            status = (
                FinalAttributeStatus.REJECTED
                if blocking
                else FinalAttributeStatus.REVIEW_REQUIRED
                if error
                else FinalAttributeStatus.INFERRED
                if candidate.status == FinalAttributeStatus.INFERRED
                else FinalAttributeStatus.NORMALIZED
                if candidate.normalized_value is not None
                and candidate.normalized_value != str(candidate.raw_value)
                else FinalAttributeStatus.ENRICHED
            )
            updated.append(
                candidate.model_copy(
                    update={
                        "status": status,
                        "validation_state": "FAILED"
                        if blocking
                        else "REVIEW_REQUIRED"
                        if error
                        else "PASSED",
                    }
                )
            )
        conflict_results, conflict_reviews = self._conflicts(product, updated)
        results.extend(conflict_results)
        reviews = list(conflict_reviews)
        for candidate in updated:
            failures = tuple(
                item
                for item in results
                if item.attribute == candidate.attribute_id
                and item.severity in {ValidationSeverity.ERROR, ValidationSeverity.BLOCKING}
            )
            if failures or candidate.status in {
                FinalAttributeStatus.REJECTED,
                FinalAttributeStatus.REVIEW_REQUIRED,
            }:
                reviews.append(
                    ReviewPayload(
                        product_id=product.product_id,
                        attribute=candidate.attribute_id,
                        current_value=_current_value(product, candidate.attribute_id),
                        candidate_values=(candidate.value,),
                        sources=tuple(filter(None, (candidate.source_id,))),
                        evidence=candidate.evidence,
                        validation_failures=failures,
                        recommended_action="review_candidate",
                        reason="Deterministic validation did not establish publishability.",
                    )
                )
        return tuple(updated), tuple(results), tuple(_dedupe_reviews(reviews))

    def publication_state(
        self,
        plans: Iterable[AttributePlan],
        candidates: Iterable[EnrichmentCandidate],
        validations: Iterable[ValidationResult],
        reviews: Iterable[ReviewPayload],
    ) -> PublicationState:
        plan_items = tuple(plans)
        candidate_items = tuple(candidates)
        validation_items = tuple(validations)
        if not plan_items:
            return PublicationState.READY
        if any(item.severity == ValidationSeverity.BLOCKING for item in validation_items):
            return PublicationState.BLOCKED
        required = {
            item.attribute_id for item in plan_items if item.applicability.value == "REQUIRED"
        }
        satisfied = {
            item.attribute_id
            for item in candidate_items
            if item.attribute_id in required
            and item.status
            not in {FinalAttributeStatus.REJECTED, FinalAttributeStatus.REVIEW_REQUIRED}
        }
        if required - satisfied:
            return PublicationState.BLOCKED
        if tuple(reviews) or any(
            item.severity == ValidationSeverity.ERROR
            or (
                item.severity == ValidationSeverity.WARNING
                and item.validator == "evidence_directness"
            )
            for item in validation_items
        ):
            return PublicationState.REVIEW_REQUIRED
        return PublicationState.READY

    def _validate_one(
        self, product: ProductTruth, plan: AttributePlan | None, candidate: EnrichmentCandidate
    ) -> tuple[ValidationResult, ...]:
        output: list[ValidationResult] = []
        if plan is None:
            output.append(
                ValidationResult(
                    validator="schema",
                    passed=False,
                    severity=ValidationSeverity.BLOCKING,
                    message="Candidate attribute is not present in the deterministic plan.",
                    attribute=candidate.attribute_id,
                    actual_value=candidate.value,
                    expected_condition="planned attribute",
                )
            )
            return tuple(output)
        if not candidate.value and candidate.value != 0:
            output.append(
                ValidationResult(
                    validator="format",
                    passed=False,
                    severity=ValidationSeverity.BLOCKING,
                    message="Empty candidate values are not publishable.",
                    attribute=candidate.attribute_id,
                    actual_value=candidate.value,
                    expected_condition="non-empty value",
                )
            )
        if plan.applicability.value not in {"REQUIRED", "OPTIONAL"}:
            output.append(
                ValidationResult(
                    validator="applicability",
                    passed=False,
                    severity=ValidationSeverity.BLOCKING,
                    message="Candidate is not applicable under the current plan.",
                    attribute=candidate.attribute_id,
                    actual_value=candidate.value,
                    expected_condition="applicable attribute",
                )
            )
        source_ids = set(candidate.evidence_ids)
        evidence_ids = {item.evidence_id for item in candidate.evidence}
        if not source_ids or not source_ids.issubset(evidence_ids) or not candidate.evidence_text:
            output.append(
                ValidationResult(
                    validator="evidence",
                    passed=False,
                    severity=ValidationSeverity.BLOCKING,
                    message="Every candidate requires traceable source evidence.",
                    attribute=candidate.attribute_id,
                    expected_condition="evidence ID and quoted text",
                )
            )
        source = next(
            (item for item in product.sources if item.source_id == candidate.source_id), None
        )
        if source is None or source.status != SourceStatus.AVAILABLE:
            output.append(
                ValidationResult(
                    validator="source_policy",
                    passed=False,
                    severity=ValidationSeverity.BLOCKING,
                    message="Candidate source is unavailable or unknown.",
                    attribute=candidate.attribute_id,
                    evidence_reference=candidate.source_id,
                )
            )
        elif source.source_type not in {
            SourceType.MANUFACTURER_PAGE,
            SourceType.MANUFACTURER_DOCUMENT,
            SourceType.MANUFACTURER_CATALOG,
        } or source.authority not in {SourceAuthority.AUTHORITATIVE, SourceAuthority.HIGH}:
            output.append(
                ValidationResult(
                    validator="source_policy",
                    passed=False,
                    severity=ValidationSeverity.BLOCKING,
                    message="Only authoritative/high manufacturer sources may support enrichment.",
                    attribute=candidate.attribute_id,
                    evidence_reference=candidate.source_id,
                )
            )
        if plan.allowed_values:
            actual = (candidate.normalized_value or str(candidate.value)).casefold()
            allowed = {value.casefold() for value in plan.allowed_values}
            if actual not in allowed:
                output.append(
                    ValidationResult(
                        validator="lov",
                        passed=False,
                        severity=ValidationSeverity.ERROR,
                        message="Candidate is outside the applicable controlled vocabulary.",
                        attribute=candidate.attribute_id,
                        actual_value=actual,
                        expected_condition=f"one of {sorted(allowed)}",
                        rule_reference="official LOV",
                    )
                )
        elif plan.reference_availability.value == "REFERENCE_UNAVAILABLE":
            output.append(
                ValidationResult(
                    validator="lov",
                    passed=True,
                    severity=ValidationSeverity.WARNING,
                    message="LOV validation unavailable; no compliance claim is made.",
                    attribute=candidate.attribute_id,
                    rule_reference="REFERENCE_UNAVAILABLE",
                )
            )
        if plan.allowed_uom and (candidate.uom or "") not in plan.allowed_uom:
            output.append(
                ValidationResult(
                    validator="uom",
                    passed=False,
                    severity=ValidationSeverity.ERROR,
                    message="Candidate unit is not allowed by the attribute schema.",
                    attribute=candidate.attribute_id,
                    actual_value=candidate.uom,
                    expected_condition=f"one of {list(plan.allowed_uom)}",
                )
            )
        elif (
            candidate.uom
            and not plan.allowed_uom
            and plan.reference_availability.value == "REFERENCE_UNAVAILABLE"
        ):
            output.append(
                ValidationResult(
                    validator="uom",
                    passed=True,
                    severity=ValidationSeverity.WARNING,
                    message="UOM reference validation unavailable; unit preserved verbatim.",
                    attribute=candidate.attribute_id,
                    rule_reference="REFERENCE_UNAVAILABLE",
                )
            )
        if candidate.status == FinalAttributeStatus.INFERRED:
            output.append(
                ValidationResult(
                    validator="evidence_directness",
                    passed=True,
                    severity=ValidationSeverity.WARNING,
                    message="Inferred/calculated candidates require review before publication.",
                    attribute=candidate.attribute_id,
                    expected_condition="direct source-backed fact or explicit human approval",
                )
            )
        if not output:
            output.append(
                ValidationResult(
                    validator="pipeline",
                    passed=True,
                    severity=ValidationSeverity.INFO,
                    message="Candidate passed deterministic validation.",
                    attribute=candidate.attribute_id,
                    actual_value=candidate.value,
                )
            )
        return tuple(output)

    @staticmethod
    def _conflicts(
        product: ProductTruth, candidates: Iterable[EnrichmentCandidate]
    ) -> tuple[list[ValidationResult], list[ReviewPayload]]:
        grouped: defaultdict[str, list[EnrichmentCandidate]] = defaultdict(list)
        for item in candidates:
            if item.status not in {FinalAttributeStatus.REJECTED}:
                grouped[item.attribute_id].append(item)
        results: list[ValidationResult] = []
        reviews: list[ReviewPayload] = []
        for attribute_id, values in grouped.items():
            distinct = {str(item.normalized_value or item.value).casefold() for item in values}
            if len(distinct) <= 1:
                continue
            results.append(
                ValidationResult(
                    validator="conflict_detection",
                    passed=False,
                    severity=ValidationSeverity.ERROR,
                    message="Multiple evidence-backed values disagree.",
                    attribute=attribute_id,
                    expected_condition="one consistent value or explicit resolution",
                )
            )
            reviews.append(
                ReviewPayload(
                    product_id=product.product_id,
                    attribute=attribute_id,
                    current_value=_current_value(product, attribute_id),
                    candidate_values=tuple(item.value for item in values),
                    sources=tuple(item.source_id or "" for item in values),
                    evidence=tuple(ref for item in values for ref in item.evidence),
                    validation_failures=(results[-1],),
                    recommended_action="resolve_conflict",
                    reason="Conflicting manufacturer evidence must not be silently overwritten.",
                )
            )
        return results, reviews


def _current_value(product: ProductTruth, attribute_id: str) -> object:
    try:
        return product.attribute(attribute_id).normalized_value
    except KeyError:
        return None


def _dedupe_reviews(reviews: Iterable[ReviewPayload]) -> list[ReviewPayload]:
    seen: set[tuple[str, str, str]] = set()
    result: list[ReviewPayload] = []
    for review in reviews:
        key = (review.product_id, review.attribute, review.reason)
        if key not in seen:
            seen.add(key)
            result.append(review)
    return result
