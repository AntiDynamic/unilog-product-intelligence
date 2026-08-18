"""Canonical ProductTruth domain model and its explicit lifecycle vocabulary."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ValueStatus(StrEnum):
    """Lifecycle status for a value or attribute candidate."""

    MISSING = "missing"
    CANDIDATE = "candidate"
    INFERRED = "inferred"
    NORMALIZED = "normalized"
    ENRICHED = "enriched"
    VERIFIED = "verified"
    CONFLICTED = "conflicted"
    REJECTED = "rejected"


class LifecycleState(StrEnum):
    """Product-level lifecycle states permitted by the domain."""

    RAW = "raw"
    UNDERSTOOD = "understood"
    CLASSIFIED = "classified"
    ENRICHED = "enriched"
    VALIDATED = "validated"
    READY = "ready"
    DELIVERED = "delivered"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"
    CONFLICTED = "conflicted"


class SourceType(StrEnum):
    """Allowed source categories; authority is a separate explicit field."""

    SUPPLIED_INPUT = "supplied_input"
    UNILOG_MASTER_DATA = "unilog_master_data"
    UNILOG_RULE = "unilog_rule"
    MANUFACTURER_PAGE = "manufacturer_page"
    MANUFACTURER_DOCUMENT = "manufacturer_document"
    MANUFACTURER_CATALOG = "manufacturer_catalog"
    AUTHORIZED_DISTRIBUTOR = "authorized_distributor"
    OTHER_PERMITTED_SOURCE = "other_permitted_source"
    MODEL_INFERENCE = "model_inference"


class SourceAuthority(StrEnum):
    """Qualitative source authority, not a calibrated confidence score."""

    AUTHORITATIVE = "authoritative"
    HIGH = "high"
    MEDIUM = "medium"
    SECONDARY = "secondary"
    LOW = "low"
    UNKNOWN = "unknown"


class SourceStatus(StrEnum):
    """Operational status of a source reference."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class EvidenceType(StrEnum):
    """Concise evidence classes; no hidden reasoning is stored."""

    DIRECT_TEXT = "direct_text"
    TABLE_CELL = "table_cell"
    IMAGE_REGION = "image_region"
    STRUCTURED_FIELD = "structured_field"
    RULE_DERIVED = "rule_derived"
    CALCULATED = "calculated"
    MODEL_INFERENCE = "model_inference"


class ValidationState(StrEnum):
    """Application validation result for a candidate or product."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"


class ConflictState(StrEnum):
    """Conflict resolution lifecycle."""

    OPEN = "open"
    RECOMMENDATION_AVAILABLE = "recommendation_available"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ConflictType(StrEnum):
    """Known conflict categories without assuming a resolution policy."""

    VALUE_DISAGREEMENT = "value_disagreement"
    SOURCE_DISAGREEMENT = "source_disagreement"
    IDENTITY_DISAGREEMENT = "identity_disagreement"
    CLASSIFICATION_DISAGREEMENT = "classification_disagreement"


class AttributeApplicability(StrEnum):
    """Whether an attribute applies to the product under review."""

    UNKNOWN = "unknown"
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    REVIEW_REQUIRED = "review_required"


class AssetType(StrEnum):
    """Digital asset categories supported by the canonical model."""

    IMAGE = "image"
    PRIMARY_IMAGE = "primary_image"
    ALTERNATE_IMAGE = "alternate_image"
    DOCUMENT = "document"
    SPECIFICATION_SHEET = "specification_sheet"
    TECHNICAL_DATA_SHEET = "technical_data_sheet"
    INSTALLATION_MANUAL = "installation_manual"
    USER_MANUAL = "user_manual"
    MANUAL = "manual"
    WARRANTY = "warranty"
    SDS = "sds"
    CATALOG = "catalog"
    BROCHURE = "brochure"
    CAD_DRAWING = "cad_drawing"
    TECHNICAL_DRAWING = "technical_drawing"
    OTHER_DOCUMENT = "other_document"
    OTHER = "other"


class DomainModel(BaseModel):
    """Shared strict Pydantic configuration for semantic domain entities."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RawInputField(DomainModel):
    """Immutable source field snapshot used to answer what the input contained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_name: str
    raw_value: Any = None
    normalized_value: str | None = None
    normalization_reason: str | None = None
    source_id: str


class Source(DomainModel):
    """First-class source reference with explicit authority and operational status."""

    source_id: str
    source_type: SourceType
    authority: SourceAuthority = SourceAuthority.UNKNOWN
    uri: str | None = None
    manufacturer_id: str | None = None
    retrieved_at: datetime | None = None
    content_hash: str | None = None
    status: SourceStatus = SourceStatus.AVAILABLE
    metadata: dict[str, str] = Field(default_factory=dict)


class Evidence(DomainModel):
    """Concise, source-linked evidence for a product or attribute fact."""

    evidence_id: str
    source_id: str
    product_id: str | None = None
    attribute_id: str | None = None
    candidate_id: str | None = None
    quoted_text: str | None = None
    document_page: int | None = Field(default=None, ge=1)
    location: dict[str, str] = Field(default_factory=dict)
    extracted_at: datetime | None = None
    evidence_type: EvidenceType


class AssessmentMetadata(DomainModel):
    """Separate measurable assessment factors; deliberately no aggregate AI score."""

    model_confidence: float | None = Field(default=None, ge=0, le=1)
    source_authority: SourceAuthority = SourceAuthority.UNKNOWN
    evidence_available: bool = False
    validation_state: ValidationState = ValidationState.PENDING
    normalization_applied: bool = False
    source_agreement: str = "unknown"


class IdentityField(DomainModel):
    """Identity value with raw/canonical forms and source links."""

    raw_value: Any = None
    normalized_value: str | None = None
    status: ValueStatus = ValueStatus.MISSING
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    assessment: AssessmentMetadata = Field(default_factory=AssessmentMetadata)


class ProductIdentity(DomainModel):
    """Semantic product identity, separate from the delivery representation."""

    manufacturer: IdentityField | None = None
    manufacturer_code: IdentityField | None = None
    brand: IdentityField | None = None
    brand_code: IdentityField | None = None
    manufacturer_part_number: IdentityField | None = None
    source_part_number: IdentityField | None = None
    sku: IdentityField | None = None
    trade_name: IdentityField | None = None
    source_record_id: str | None = None


class ProductClassification(DomainModel):
    """Semantic classification fields with source/evidence linkage."""

    department: str | None = None
    class_name: str | None = None
    fine: str | None = None
    classpath: tuple[str, ...] = ()
    taxonomy_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    validation_state: ValidationState = ValidationState.PENDING


class CandidateValue(DomainModel):
    """One candidate value; candidates coexist until an explicit decision is made."""

    candidate_id: str
    raw_value: Any = None
    normalized_value: str | None = None
    uom: str | None = None
    status: ValueStatus = ValueStatus.CANDIDATE
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    assessment: AssessmentMetadata = Field(default_factory=AssessmentMetadata)
    created_at: datetime | None = None


class AttributeRecord(DomainModel):
    """Structured attribute record, not a flat key-value pair."""

    attribute_id: str
    canonical_name: str
    raw_value: Any = None
    normalized_value: str | None = None
    uom: str | None = None
    applicability: AttributeApplicability = AttributeApplicability.UNKNOWN
    status: ValueStatus = ValueStatus.MISSING
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    candidates: list[CandidateValue] = Field(default_factory=list)
    assessment: AssessmentMetadata = Field(default_factory=AssessmentMetadata)
    validation_state: ValidationState = ValidationState.PENDING


class ProductDescriptions(DomainModel):
    """Channel-neutral description facts generated later from ProductTruth."""

    invoice: str | None = None
    mobile: str | None = None
    short: str | None = None
    long: str | None = None
    retail: str | None = None
    marketing: str | None = None
    features: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class DigitalAsset(DomainModel):
    """Reference to an image/document without downloading or inventing assets."""

    asset_id: str
    asset_type: AssetType
    uri: str
    source_id: str
    title: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    manufacturer_domain: str | None = None
    product_id: str | None = None
    association_scope: str = "PRODUCT_SPECIFIC"
    content_status: str = "NOT_PARSED"
    confidence: float = 1.0
    evidence_ids: list[str] = Field(default_factory=list)
    status: SourceStatus = SourceStatus.AVAILABLE
    discovered_from: str | None = None
    description: str | None = None


class Conflict(DomainModel):
    """First-class disagreement between candidate values or sources."""

    conflict_id: str
    product_id: str
    attribute_id: str | None = None
    candidate_ids: list[str] = Field(min_length=2)
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    conflict_type: ConflictType
    state: ConflictState = ConflictState.OPEN
    recommended_candidate_id: str | None = None
    resolution_reason: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None


class ValidationEvent(DomainModel):
    """Append-oriented validation result for an entity or candidate."""

    event_id: str
    product_id: str
    validation_state: ValidationState
    code: str
    message: str
    attribute_id: str | None = None
    candidate_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class AuditEvent(DomainModel):
    """Append-only decision trace without hidden chain-of-thought."""

    event_id: str
    product_id: str
    event_type: str
    actor: str
    details: dict[str, str] = Field(default_factory=dict)
    created_at: datetime | None = None


class ProductQuality(DomainModel):
    """Explicit quality factors; no uncalibrated aggregate confidence score."""

    known_field_count: int = Field(default=0, ge=0)
    populated_field_count: int = Field(default=0, ge=0)
    unresolved_issue_count: int = Field(default=0, ge=0)
    validation_state: ValidationState = ValidationState.PENDING
    readiness_state: LifecycleState = LifecycleState.RAW
    conflict_count: int = Field(default=0, ge=0)
    unresolved_issue_codes: list[str] = Field(default_factory=list)


class ProductTruth(DomainModel):
    """Canonical semantic product representation between input and delivery adapters."""

    product_id: str = ""
    identity: ProductIdentity = Field(default_factory=ProductIdentity)
    classification: ProductClassification = Field(default_factory=ProductClassification)
    attributes: list[AttributeRecord] = Field(default_factory=list)
    descriptions: ProductDescriptions = Field(default_factory=ProductDescriptions)
    digital_assets: list[DigitalAsset] = Field(default_factory=list)
    raw_inputs: tuple[RawInputField, ...] = ()
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    validation_events: list[ValidationEvent] = Field(default_factory=list)
    audit_events: list[AuditEvent] = Field(default_factory=list)
    lifecycle_state: LifecycleState = LifecycleState.RAW
    quality: ProductQuality = Field(default_factory=ProductQuality)

    @property
    def classification_path(self) -> list[str]:
        """Compatibility view of the semantic classification path."""

        return list(self.classification.classpath)

    def raw_value(self, field_name: str) -> Any:
        """Return the immutable raw value for a source field, if present."""

        for field in self.raw_inputs:
            if field.field_name == field_name:
                return field.raw_value
        return None

    def attribute(self, attribute_id: str) -> AttributeRecord:
        """Find one structured attribute or raise a clear domain error."""

        for attribute in self.attributes:
            if attribute.attribute_id == attribute_id:
                return attribute
        raise KeyError(f"Unknown attribute: {attribute_id}")
