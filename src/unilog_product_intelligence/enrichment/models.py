"""Typed Phase 6 contracts.

These models deliberately keep model proposals, evidence, validation, and publication state
separate.  A provider response is never itself a publishable value.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EnrichmentDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FinalAttributeStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NORMALIZED = "NORMALIZED"
    ENRICHED = "ENRICHED"
    INFERRED = "INFERRED"
    CONFLICTED = "CONFLICTED"
    MISSING = "MISSING"
    REJECTED = "REJECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class Applicability(StrEnum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class EnrichmentDecision(StrEnum):
    NO_ACTION = "NO_ACTION"
    VERIFY_EXISTING = "VERIFY_EXISTING"
    ENRICH = "ENRICH"
    REVIEW = "REVIEW"


class ReferenceAvailability(StrEnum):
    REFERENCE_AVAILABLE = "REFERENCE_AVAILABLE"
    REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"


class ValidationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKING = "BLOCKING"


class PublicationState(StrEnum):
    READY = "READY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


class EnrichmentStatus(StrEnum):
    PLANNING_ATTRIBUTES = "PLANNING_ATTRIBUTES"
    ENRICHING = "ENRICHING"
    VALIDATING_ATTRIBUTES = "VALIDATING_ATTRIBUTES"
    REPAIRING = "REPAIRING"
    CONFLICT_REVIEW = "CONFLICT_REVIEW"
    ENRICHED = "ENRICHED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


class EvidenceReference(EnrichmentDTO):
    evidence_id: str
    source_id: str
    source_url: str | None = None
    source_type: str | None = None
    source_authority: str | None = None
    source_content_hash: str | None = None
    evidence_text: str
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    retrieved_at: datetime | None = None
    document_chunk: str | None = None


class AttributeSchema(EnrichmentDTO):
    attribute_id: str
    canonical_name: str
    required: bool = False
    value_type: str = "text"
    allowed_values: tuple[str, ...] = ()
    allowed_uom: tuple[str, ...] = ()
    reference_availability: ReferenceAvailability = ReferenceAvailability.REFERENCE_UNAVAILABLE
    classpaths: tuple[str, ...] = ()
    reason: str = "deterministic category schema"


class AttributePlan(EnrichmentDTO):
    product_id: str
    category: str | None = None
    classpath: tuple[str, ...] = ()
    attribute_id: str
    attribute_name: str
    applicability: Applicability
    current_status: FinalAttributeStatus
    current_value: Any = None
    evidence_available: bool = False
    enrichment_required: EnrichmentDecision = EnrichmentDecision.NO_ACTION
    validation_requirements: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()
    allowed_uom: tuple[str, ...] = ()
    reference_availability: ReferenceAvailability = ReferenceAvailability.REFERENCE_UNAVAILABLE
    priority: int = Field(default=50, ge=0, le=100)
    reason: str


class EnrichmentCandidate(EnrichmentDTO):
    candidate_id: str
    product_id: str
    attribute_id: str
    attribute: str
    value: Any = None
    raw_value: Any = None
    normalized_value: str | None = None
    uom: str | None = None
    source_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    evidence_text: str | None = None
    evidence: tuple[EvidenceReference, ...] = ()
    status: FinalAttributeStatus = FinalAttributeStatus.ENRICHED
    candidate_reason: str
    model_metadata: dict[str, str] = Field(default_factory=dict)
    validation_state: str = "PENDING"
    cache_key: str | None = None


class ValidationResult(EnrichmentDTO):
    validator: str
    passed: bool
    severity: ValidationSeverity
    message: str
    field: str | None = None
    attribute: str | None = None
    evidence_reference: str | None = None
    rule_reference: str | None = None
    actual_value: Any = None
    expected_condition: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewPayload(EnrichmentDTO):
    product_id: str
    attribute: str
    current_value: Any = None
    candidate_values: tuple[Any, ...] = ()
    sources: tuple[str, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
    validation_failures: tuple[ValidationResult, ...] = ()
    recommended_action: str
    reason: str


class EnrichmentMetrics(EnrichmentDTO):
    products: int = 0
    planned_attributes: int = 0
    enriched_attributes: int = 0
    accepted_candidates: int = 0
    rejected_candidates: int = 0
    review_attributes: int = 0
    missing_attributes: int = 0
    conflicts: int = 0
    ready: int = 0
    review_required: int = 0
    blocked: int = 0
    agent_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    retries: int = 0
    estimated_cost_usd: float = 0.0


class EnrichmentResult(EnrichmentDTO):
    product_id: str
    status: EnrichmentStatus
    publication_state: PublicationState
    attribute_plans: tuple[AttributePlan, ...] = ()
    candidates: tuple[EnrichmentCandidate, ...] = ()
    validations: tuple[ValidationResult, ...] = ()
    reviews: tuple[ReviewPayload, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    reference_availability: ReferenceAvailability = ReferenceAvailability.REFERENCE_UNAVAILABLE
    product_truth: Any = None
    error: str | None = None
    metrics: EnrichmentMetrics = Field(default_factory=EnrichmentMetrics)


class CandidateResponse(EnrichmentDTO):
    """Small provider contract; all evidence is supplied by the application."""

    attribute: str
    value: Any = None
    raw_value: Any = None
    normalized_value: str | None = None
    uom: str | None = None
    evidence_id: str | None = None
    evidence_text: str | None = None
    status: str = "DIRECT"
    reason: str = "Source-backed candidate."


class CandidateResponseEnvelope(EnrichmentDTO):
    candidates: list[CandidateResponse] = Field(default_factory=list)
    unresolved_attributes: list[str] = Field(default_factory=list)
