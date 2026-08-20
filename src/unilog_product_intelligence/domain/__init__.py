"""Semantic domain models and lifecycle rules."""

from .conflicts import ConflictResolution, EvidenceConflict
from .evidence_packet import ProductEvidencePacket
from .lifecycle import ALLOWED_TRANSITIONS, InvalidLifecycleTransition, assert_transition
from .models import DiscoveredAsset, FeatureEvidence, StructuredSpec
from .truth import ProductTruth  # noqa: F401

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ConflictResolution",
    "DiscoveredAsset",
    "EvidenceConflict",
    "FeatureEvidence",
    "InvalidLifecycleTransition",
    "ProductEvidencePacket",
    "ProductTruth",
    "StructuredSpec",
    "assert_transition",
]
