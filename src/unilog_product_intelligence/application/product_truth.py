"""Deterministic ProductTruth service boundary for later persistence and enrichment."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from unilog_product_intelligence.data.normalize import normalize_value
from unilog_product_intelligence.domain.lifecycle import assert_transition
from unilog_product_intelligence.domain.truth import (
    AssessmentMetadata,
    AttributeRecord,
    AuditEvent,
    CandidateValue,
    Conflict,
    ConflictState,
    Evidence,
    IdentityField,
    LifecycleState,
    ProductClassification,
    ProductIdentity,
    ProductQuality,
    ProductTruth,
    RawInputField,
    Source,
    SourceAuthority,
    ValidationEvent,
    ValidationState,
    ValueStatus,
)


class ProductTruthOperations(Protocol):
    """Use-case port for canonical product operations."""

    def create_from_raw_input(
        self, product_id: str, raw_values: Mapping[str, object], source: Source
    ) -> ProductTruth: ...

    def update_identity(self, product: ProductTruth, identity: ProductIdentity) -> ProductTruth: ...

    def add_classification(
        self, product: ProductTruth, classification: ProductClassification
    ) -> ProductTruth: ...

    def add_attribute_candidate(
        self,
        product: ProductTruth,
        attribute_id: str,
        candidate: CandidateValue,
        canonical_name: str,
    ) -> ProductTruth: ...

    def attach_evidence(self, product: ProductTruth, evidence: Evidence) -> ProductTruth: ...

    def validate_candidate(
        self,
        product: ProductTruth,
        attribute_id: str,
        candidate_id: str,
        accepted: bool,
        reason: str,
    ) -> ProductTruth: ...

    def create_conflict(self, product: ProductTruth, conflict: Conflict) -> ProductTruth: ...

    def resolve_conflict(
        self, product: ProductTruth, conflict_id: str, candidate_id: str, reason: str, actor: str
    ) -> ProductTruth: ...


def _now() -> datetime:
    return datetime.now(UTC)


def _event(
    product_id: str, event_type: str, details: dict[str, str], actor: str = "system"
) -> AuditEvent:
    return AuditEvent(
        event_id=str(uuid4()),
        product_id=product_id,
        event_type=event_type,
        actor=actor,
        details=details,
        created_at=_now(),
    )


def _copy(product: ProductTruth) -> ProductTruth:
    return product.model_copy(deep=True)


class ProductTruthService:
    """Pure deterministic service; it performs no Gemini calls or web retrieval."""

    def create_from_raw_input(
        self, product_id: str, raw_values: Mapping[str, object], source: Source
    ) -> ProductTruth:
        """Create canonical structure while preserving every supplied field verbatim."""

        normalized_fields = {name: normalize_value(value) for name, value in raw_values.items()}
        raw_inputs = tuple(
            RawInputField(
                field_name=name,
                raw_value=value.raw_value,
                normalized_value=value.normalized_value,
                normalization_reason=value.reason,
                source_id=source.source_id,
            )
            for name, value in normalized_fields.items()
        )
        identity = ProductIdentity(
            manufacturer=_identity_field(normalized_fields.get("Part_Manuf"), source),
            brand=_identity_field(normalized_fields.get("Unilog_Brand"), source),
            manufacturer_part_number=_identity_field(normalized_fields.get("Mfg_Part_Num"), source),
            source_part_number=_identity_field(normalized_fields.get("Mfg_Part_Num"), source),
            source_record_id=product_id,
        )
        populated = sum(field.normalized_value is not None for field in normalized_fields.values())
        product = ProductTruth(
            product_id=product_id,
            identity=identity,
            raw_inputs=raw_inputs,
            sources=[source],
            quality=ProductQuality(
                known_field_count=len(raw_inputs),
                populated_field_count=populated,
                readiness_state=LifecycleState.RAW,
            ),
        )
        product.audit_events.append(
            _event(product_id, "product_created_from_raw_input", {"source_id": source.source_id})
        )
        return product

    def update_identity(self, product: ProductTruth, identity: ProductIdentity) -> ProductTruth:
        result = _copy(product)
        result.identity = identity
        result.audit_events.append(_event(product.product_id, "identity_updated", {}))
        return result

    def add_classification(
        self, product: ProductTruth, classification: ProductClassification | dict[str, Any]
    ) -> ProductTruth:
        if isinstance(classification, dict):
            classification = ProductClassification(**classification)
        result = _copy(product)
        if result.lifecycle_state == LifecycleState.RAW:
            _transition(result, LifecycleState.UNDERSTOOD, "classification_input_received")
        if result.lifecycle_state == LifecycleState.UNDERSTOOD:
            _transition(result, LifecycleState.CLASSIFIED, "classification_added")
        elif result.lifecycle_state != LifecycleState.CLASSIFIED:
            raise ValueError("Classification can only be added before enrichment")
        result.classification = classification
        result.audit_events.append(_event(product.product_id, "classification_added", {}))
        return result

    def add_attribute_candidate(
        self,
        product: ProductTruth,
        attribute_id: str,
        candidate: CandidateValue,
        canonical_name: str,
    ) -> ProductTruth:
        result = _copy(product)
        if result.lifecycle_state not in {
            LifecycleState.CLASSIFIED,
            LifecycleState.ENRICHED,
            LifecycleState.CONFLICTED,
        }:
            raise ValueError("Attribute candidates require a classified product")
        try:
            attribute = result.attribute(attribute_id)
        except KeyError:
            attribute = AttributeRecord(attribute_id=attribute_id, canonical_name=canonical_name)
            result.attributes.append(attribute)
        attribute.candidates.append(candidate)
        attribute.status = ValueStatus.CANDIDATE
        attribute.source_ids = sorted(set(attribute.source_ids + candidate.source_ids))
        if result.lifecycle_state == LifecycleState.CLASSIFIED:
            _transition(result, LifecycleState.ENRICHED, "attribute_candidate_added")
        result.audit_events.append(
            _event(
                product.product_id,
                "attribute_candidate_added",
                {"attribute_id": attribute_id, "candidate_id": candidate.candidate_id},
            )
        )
        return result

    def attach_evidence(self, product: ProductTruth, evidence: Evidence) -> ProductTruth:
        result = _copy(product)
        if not any(source.source_id == evidence.source_id for source in result.sources):
            raise ValueError(f"Evidence references unknown source: {evidence.source_id}")
        result.evidence.append(evidence)
        if evidence.attribute_id:
            attribute = result.attribute(evidence.attribute_id)
            attribute.evidence_ids = sorted(set(attribute.evidence_ids + [evidence.evidence_id]))
            for candidate in attribute.candidates:
                if evidence.candidate_id == candidate.candidate_id:
                    candidate.evidence_ids = sorted(
                        set(candidate.evidence_ids + [evidence.evidence_id])
                    )
                if evidence.evidence_id in candidate.evidence_ids:
                    candidate.assessment.evidence_available = True
        result.audit_events.append(
            _event(product.product_id, "evidence_attached", {"evidence_id": evidence.evidence_id})
        )
        return result

    def validate_candidate(
        self,
        product: ProductTruth,
        attribute_id: str,
        candidate_id: str,
        accepted: bool,
        reason: str,
    ) -> ProductTruth:
        result = _copy(product)
        attribute = result.attribute(attribute_id)
        candidate = next(
            (item for item in attribute.candidates if item.candidate_id == candidate_id), None
        )
        if candidate is None:
            raise KeyError(f"Unknown candidate: {candidate_id}")
        if accepted and not candidate.evidence_ids:
            raise ValueError("A candidate cannot be accepted without evidence")
        if accepted:
            authorities = [
                source.authority
                for source in result.sources
                if source.source_id in candidate.source_ids
            ]
            candidate.status = (
                ValueStatus.VERIFIED
                if authorities
                and all(
                    value in {SourceAuthority.AUTHORITATIVE, SourceAuthority.HIGH}
                    for value in authorities
                )
                else ValueStatus.INFERRED
            )
            candidate.assessment.validation_state = ValidationState.PASSED
            attribute.validation_state = ValidationState.PASSED
        else:
            candidate.status = ValueStatus.REJECTED
            candidate.assessment.validation_state = ValidationState.FAILED
            attribute.validation_state = ValidationState.FAILED
        result.validation_events.append(
            ValidationEvent(
                event_id=str(uuid4()),
                product_id=product.product_id,
                attribute_id=attribute_id,
                candidate_id=candidate_id,
                validation_state=candidate.assessment.validation_state,
                code="candidate_validation",
                message=reason,
                evidence_ids=list(candidate.evidence_ids),
                created_at=_now(),
            )
        )
        result.audit_events.append(
            _event(product.product_id, "candidate_validated", {"candidate_id": candidate_id})
        )
        return result

    def create_conflict(self, product: ProductTruth, conflict: Conflict) -> ProductTruth:
        result = _copy(product)
        if conflict.product_id != product.product_id:
            raise ValueError("Conflict product_id does not match ProductTruth")
        attribute = result.attribute(conflict.attribute_id) if conflict.attribute_id else None
        candidate_ids = (
            {candidate.candidate_id for candidate in attribute.candidates} if attribute else set()
        )
        if not set(conflict.candidate_ids).issubset(candidate_ids):
            raise ValueError("Conflict references a candidate not attached to the product")
        result.conflicts.append(conflict)
        result.quality.conflict_count = len(result.conflicts)
        if result.lifecycle_state in {LifecycleState.CLASSIFIED, LifecycleState.ENRICHED}:
            _transition(result, LifecycleState.CONFLICTED, "conflict_created")
        result.audit_events.append(
            _event(product.product_id, "conflict_created", {"conflict_id": conflict.conflict_id})
        )
        return result

    def resolve_conflict(
        self, product: ProductTruth, conflict_id: str, candidate_id: str, reason: str, actor: str
    ) -> ProductTruth:
        result = _copy(product)
        conflict = next(
            (item for item in result.conflicts if item.conflict_id == conflict_id), None
        )
        if conflict is None:
            raise KeyError(f"Unknown conflict: {conflict_id}")
        if candidate_id not in conflict.candidate_ids:
            raise ValueError("Resolution candidate is not part of the conflict")
        if conflict.state not in {ConflictState.OPEN, ConflictState.RECOMMENDATION_AVAILABLE}:
            raise ValueError("Only open conflicts can be resolved")
        conflict.state = ConflictState.RESOLVED
        conflict.recommended_candidate_id = candidate_id
        conflict.resolution_reason = reason
        conflict.resolved_by = actor
        conflict.resolved_at = _now()
        result.audit_events.append(
            _event(product.product_id, "conflict_resolved", {"conflict_id": conflict_id}, actor)
        )
        return result


def _identity_field(value: object | None, source: Source) -> IdentityField | None:
    if value is None:
        return None
    normalized = getattr(value, "normalized_value", None)
    raw = getattr(value, "raw_value", value)
    reason = getattr(value, "reason", None)
    return IdentityField(
        raw_value=raw,
        normalized_value=normalized,
        status=ValueStatus.MISSING if normalized is None else ValueStatus.NORMALIZED,
        source_ids=[source.source_id],
        assessment=AssessmentMetadata(
            source_authority=source.authority,
            evidence_available=True,
            normalization_applied=reason is not None,
        ),
    )


def _transition(product: ProductTruth, target: LifecycleState, reason: str) -> None:
    assert_transition(product.lifecycle_state, target)
    previous = product.lifecycle_state
    product.lifecycle_state = target
    product.quality.readiness_state = target
    product.audit_events.append(
        _event(
            product.product_id,
            "lifecycle_transition",
            {"from": previous, "to": target, "reason": reason},
        )
    )
