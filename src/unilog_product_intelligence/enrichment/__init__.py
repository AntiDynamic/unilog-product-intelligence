"""Evidence-grounded product enrichment (Phase 6)."""

from .agent import EvidenceGroundedEnrichmentAgent
from .models import (
    AttributePlan,
    AttributeSchema,
    EnrichmentCandidate,
    EnrichmentResult,
    EnrichmentStatus,
    FinalAttributeStatus,
    PublicationState,
    ReferenceAvailability,
    ReviewPayload,
    ValidationResult,
)
from .persistence import EnrichmentPersistence, PostgresEnrichmentRepository
from .planner import AttributePlanner, ReferencePack
from .service import EnrichmentService
from .validation import ValidationPipeline

__all__ = [
    "AttributePlan",
    "AttributePlanner",
    "AttributeSchema",
    "EnrichmentCandidate",
    "EvidenceGroundedEnrichmentAgent",
    "EnrichmentResult",
    "EnrichmentPersistence",
    "EnrichmentService",
    "EnrichmentStatus",
    "FinalAttributeStatus",
    "PostgresEnrichmentRepository",
    "PublicationState",
    "ReferenceAvailability",
    "ReferencePack",
    "ReviewPayload",
    "ValidationPipeline",
    "ValidationResult",
]
