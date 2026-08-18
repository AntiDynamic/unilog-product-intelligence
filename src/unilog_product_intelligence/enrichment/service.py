"""Application service composing planning, agent proposals, validation, and ProductTruth updates."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, datetime
from uuid import uuid4

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.source_context import VerifiedProductSourceContext
from unilog_product_intelligence.domain.truth import (
    AssessmentMetadata,
    CandidateValue,
    Conflict,
    ConflictType,
    Evidence,
    EvidenceType,
    LifecycleState,
    ProductTruth,
    SourceAuthority,
    ValidationState,
    ValueStatus,
)

from .agent import EvidenceGroundedEnrichmentAgent, evidence_references
from .descriptions import DescriptionAgent, DescriptionService
from .models import (
    AttributePlan,
    EnrichmentCandidate,
    EnrichmentMetrics,
    EnrichmentResult,
    EnrichmentStatus,
    FinalAttributeStatus,
    PublicationState,
    ValidationResult,
    ValidationSeverity,
)
from .persistence import EnrichmentPersistence
from .planner import AttributePlanner
from .validation import ValidationPipeline


class EnrichmentService:
    """Bounded Phase 6 use case; agents never access persistence or arbitrary SQL."""

    def __init__(
        self,
        planner: AttributePlanner | None = None,
        agent: EvidenceGroundedEnrichmentAgent | None = None,
        validator: ValidationPipeline | None = None,
        truth_service: ProductTruthService | None = None,
        persistence: EnrichmentPersistence | None = None,
        description_service: DescriptionService | None = None,
    ) -> None:
        self.planner = planner or AttributePlanner()
        self.agent = agent or EvidenceGroundedEnrichmentAgent()
        self.validator = validator or ValidationPipeline()
        self.truth_service = truth_service or ProductTruthService()
        self.persistence = persistence
        self.description_service = description_service or DescriptionService(
            agent=DescriptionAgent(provider=getattr(self.agent, "provider", None))
        )

    def enrich(
        self,
        product: ProductTruth,
        source_context: VerifiedProductSourceContext | None = None,
    ) -> EnrichmentResult:
        status = EnrichmentStatus.PLANNING_ATTRIBUTES
        plans = self.planner.plan(product)
        metrics = EnrichmentMetrics(products=1, planned_attributes=len(plans))
        product = self._register_plans(product, plans)
        references = evidence_references(product)
        status = EnrichmentStatus.ENRICHING
        try:
            candidates = self.agent.enrich(
                product, plans, references, source_context=source_context
            )
        except Exception as error:
            return EnrichmentResult(
                product_id=product.product_id,
                status=EnrichmentStatus.BLOCKED,
                publication_state=PublicationState.BLOCKED,
                attribute_plans=plans,
                reference_availability=self.planner.reference_pack.availability,
                product_truth=product,
                error=type(error).__name__,
                metrics=metrics,
            )
        run = self.agent.last_run
        if run and run.response:
            metrics.agent_calls = 1
            metrics.input_tokens = run.response.input_tokens or 0
            metrics.output_tokens = run.response.output_tokens or 0
            metrics.cached_tokens = run.response.cached_tokens or 0
            metrics.retries = run.response.retry_count
            metrics.estimated_cost_usd = run.response.estimated_cost_usd or 0.0
            metrics.cache_hits = 1 if run.response.cached_tokens else 0
            metrics.cache_misses = 0 if metrics.cache_hits else 1
        status = EnrichmentStatus.VALIDATING_ATTRIBUTES
        candidates, validations, reviews = self.validator.validate(product, plans, candidates)
        repair_calls = 0
        for _attempt in range(self.agent.max_repair_attempts):
            repairable = tuple(
                item for item in candidates if item.status == FinalAttributeStatus.REVIEW_REQUIRED
            )
            if not repairable:
                break
            changed = False
            for item in repairable:
                failures = tuple(
                    validation
                    for validation in validations
                    if validation.attribute == item.attribute_id
                    and validation.severity.value in {"ERROR", "BLOCKING"}
                )
                plan = next(
                    (plan for plan in plans if plan.attribute_id == item.attribute_id), None
                )
                if plan is None or not failures:
                    continue
                repair_calls += 1
                repaired = self.agent.repair(product, plan, item, failures, references)
                if repaired is None:
                    continue
                candidates = tuple(
                    repaired if candidate.candidate_id == item.candidate_id else candidate
                    for candidate in candidates
                )
                changed = True
            if not changed:
                break
            candidates, validations, reviews = self.validator.validate(product, plans, candidates)
        metrics.agent_calls += repair_calls
        conflict_count = sum(1 for item in validations if item.validator == "conflict_detection")
        metrics.enriched_attributes = len(
            {
                item.attribute_id
                for item in candidates
                if item.status not in {FinalAttributeStatus.REJECTED}
            }
        )
        metrics.accepted_candidates = sum(
            item.status in {FinalAttributeStatus.ENRICHED, FinalAttributeStatus.NORMALIZED}
            for item in candidates
        )
        metrics.rejected_candidates = sum(
            item.status == FinalAttributeStatus.REJECTED for item in candidates
        )
        metrics.review_attributes = len(reviews)
        metrics.missing_attributes = sum(
            plan.enrichment_required.value == "ENRICH"
            and not any(candidate.attribute_id == plan.attribute_id for candidate in candidates)
            for plan in plans
        )
        metrics.conflicts = conflict_count
        publication = self.validator.publication_state(plans, candidates, validations, reviews)
        product = self._apply(product, candidates, validations, conflict_count)
        product, desc_validations = self.description_service.generate_descriptions(
            product, reference_pack=self.planner.reference_pack
        )
        blocking_desc_errors = [
            dv
            for dv in desc_validations
            if not dv.passed
            and (
                dv.severity == ValidationSeverity.BLOCKING
                or getattr(dv.severity, "value", str(dv.severity)).casefold() == "blocking"
            )
        ]
        error_desc_errors = [
            dv
            for dv in desc_validations
            if not dv.passed
            and (
                dv.severity == ValidationSeverity.ERROR
                or getattr(dv.severity, "value", str(dv.severity)).casefold() == "error"
            )
        ]
        if blocking_desc_errors:
            publication = PublicationState.BLOCKED
        elif error_desc_errors and publication == PublicationState.READY:
            publication = PublicationState.REVIEW_REQUIRED

        if publication == PublicationState.BLOCKED:
            status = EnrichmentStatus.BLOCKED
        elif publication == PublicationState.REVIEW_REQUIRED:
            status = EnrichmentStatus.REVIEW_REQUIRED
        else:
            status = EnrichmentStatus.ENRICHED
        metrics.ready = int(publication == PublicationState.READY)
        metrics.review_required = int(publication == PublicationState.REVIEW_REQUIRED)
        metrics.blocked = int(publication == PublicationState.BLOCKED)
        persistence_error: str | None = None
        if self.persistence is not None:
            try:
                self.persistence.save(
                    EnrichmentResult(
                        product_id=product.product_id,
                        status=status,
                        publication_state=publication,
                        attribute_plans=plans,
                        candidates=candidates,
                        validations=validations,
                        reviews=reviews,
                        conflict_ids=(),
                        reference_availability=self.planner.reference_pack.availability,
                        product_truth=product,
                        metrics=metrics,
                    )
                )
            except Exception as error:
                persistence_error = type(error).__name__
                publication = PublicationState.BLOCKED
                status = EnrichmentStatus.BLOCKED
                metrics.blocked = 1
                metrics.ready = 0
                metrics.review_required = 0
        return EnrichmentResult(
            product_id=product.product_id,
            status=status,
            publication_state=publication,
            attribute_plans=plans,
            candidates=candidates,
            validations=validations,
            reviews=reviews,
            conflict_ids=tuple(item.conflict_id for item in product.conflicts[-conflict_count:])
            if conflict_count
            else (),
            reference_availability=self.planner.reference_pack.availability,
            product_truth=product,
            error=persistence_error,
            metrics=metrics,
        )

    def _register_plans(
        self, product: ProductTruth, plans: Iterable[AttributePlan]
    ) -> ProductTruth:
        if product.lifecycle_state in {LifecycleState.RAW, LifecycleState.UNDERSTOOD}:
            product = self.truth_service.add_classification(product, product.classification)
        result = product
        for plan in plans:
            if not any(item.attribute_id == plan.attribute_id for item in result.attributes):
                result = _ensure_attribute(result, plan.attribute_id, plan.attribute_name)
        return result

    def _apply(
        self,
        product: ProductTruth,
        candidates: Iterable[EnrichmentCandidate],
        validations: Iterable[ValidationResult],
        conflict_count: int,
    ) -> ProductTruth:
        validation_by_attribute: dict[str, list[ValidationResult]] = {}
        for validation in validations:
            if validation.attribute:
                validation_by_attribute.setdefault(validation.attribute, []).append(validation)
        result = product
        for item in candidates:
            if item.status in {
                FinalAttributeStatus.REJECTED,
                FinalAttributeStatus.REVIEW_REQUIRED,
                FinalAttributeStatus.INFERRED,
            }:
                continue
            attribute = result.attribute(item.attribute_id)
            if any(existing.candidate_id == item.candidate_id for existing in attribute.candidates):
                continue
            candidate = CandidateValue(
                candidate_id=item.candidate_id,
                raw_value=item.raw_value,
                normalized_value=item.normalized_value
                or (str(item.value) if item.value is not None else None),
                uom=item.uom,
                status=ValueStatus.ENRICHED
                if item.status == FinalAttributeStatus.ENRICHED
                else ValueStatus.NORMALIZED,
                source_ids=[item.source_id] if item.source_id else [],
                evidence_ids=list(item.evidence_ids),
                assessment=AssessmentMetadata(
                    source_authority=next(
                        (
                            source.authority
                            for source in result.sources
                            if source.source_id == item.source_id
                        ),
                        SourceAuthority.UNKNOWN,
                    ),
                    evidence_available=True,
                    validation_state=ValidationState.PASSED,
                    normalization_applied=item.normalized_value is not None,
                ),
                created_at=datetime.now(UTC),
            )
            if any(
                value.severity.value in {"ERROR", "BLOCKING"}
                for value in validation_by_attribute.get(item.attribute_id, [])
            ):
                continue
            for ref in item.evidence:
                if not any(evidence.evidence_id == ref.evidence_id for evidence in result.evidence):
                    result = self.truth_service.attach_evidence(
                        result,
                        Evidence(
                            evidence_id=ref.evidence_id,
                            source_id=ref.source_id,
                            product_id=result.product_id,
                            attribute_id=item.attribute_id,
                            candidate_id=item.candidate_id,
                            quoted_text=ref.evidence_text,
                            document_page=ref.page,
                            location={
                                "section": ref.section or "",
                                "chunk": ref.document_chunk or "",
                            },
                            extracted_at=ref.retrieved_at or datetime.now(UTC),
                            evidence_type=EvidenceType.DIRECT_TEXT,
                        ),
                    )
            result = self.truth_service.add_attribute_candidate(
                result, item.attribute_id, candidate, item.attribute
            )
            result = self.truth_service.validate_candidate(
                result,
                item.attribute_id,
                item.candidate_id,
                True,
                item.candidate_reason,
            )
            updated = result.model_copy(deep=True)
            attribute = updated.attribute(item.attribute_id)
            attribute.raw_value = item.raw_value
            attribute.normalized_value = candidate.normalized_value
            attribute.uom = item.uom
            attribute.status = (
                ValueStatus.NORMALIZED
                if item.status == FinalAttributeStatus.NORMALIZED
                else ValueStatus.ENRICHED
            )
            result = updated
        if conflict_count:
            result = result.model_copy(deep=True)
            # Conflict objects are created only after candidates are attached.
            for attribute_id, items in _candidate_groups(result).items():
                distinct = {
                    str(item.normalized_value or item.raw_value).casefold() for item in items
                }
                if len(distinct) <= 1:
                    continue
                candidate_ids = [item.candidate_id for item in items]
                if any(
                    set(existing.candidate_ids) == set(candidate_ids)
                    for existing in result.conflicts
                ):
                    continue
                conflict = Conflict(
                    conflict_id="conflict-" + str(uuid4()),
                    product_id=result.product_id,
                    attribute_id=attribute_id,
                    candidate_ids=candidate_ids,
                    source_ids=sorted({source for item in items for source in item.source_ids}),
                    evidence_ids=sorted(
                        {evidence for item in items for evidence in item.evidence_ids}
                    ),
                    conflict_type=ConflictType.VALUE_DISAGREEMENT,
                )
                with suppress(ValueError):
                    result = self.truth_service.create_conflict(result, conflict)
        return result


def _ensure_attribute(product: ProductTruth, attribute_id: str, name: str) -> ProductTruth:
    result = product.model_copy(deep=True)
    from unilog_product_intelligence.domain.truth import AttributeRecord

    result.attributes.append(AttributeRecord(attribute_id=attribute_id, canonical_name=name))
    return result


def _candidate_groups(product: ProductTruth) -> dict[str, list[CandidateValue]]:
    return {
        attribute.attribute_id: attribute.candidates
        for attribute in product.attributes
        if len(attribute.candidates) > 1
    }
