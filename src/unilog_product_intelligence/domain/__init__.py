"""Semantic domain models and lifecycle rules."""

from .conflict_escalation import ConflictEscalationResult
from .conflicts import ConflictResolution, EvidenceConflict
from .evidence_packet import ProductEvidencePacket
from .lifecycle import ALLOWED_TRANSITIONS, InvalidLifecycleTransition, assert_transition
from .models import DiscoveredAsset, FeatureEvidence, StructuredSpec
from .provenance import FinalAttribute, ProvenanceKind
from .truth import ProductTruth  # noqa: F401

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ConflictEscalationResult",
    "ConflictResolution",
    "DiscoveredAsset",
    "EvidenceConflict",
    "FeatureEvidence",
    "FinalAttribute",
    "InvalidLifecycleTransition",
    "ProductEvidencePacket",
    "ProductTruth",
    "ProvenanceKind",
    "StructuredSpec",
    "assert_transition",
]
