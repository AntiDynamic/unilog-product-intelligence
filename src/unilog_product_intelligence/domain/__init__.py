"""Semantic domain models and lifecycle rules."""

from .conflicts import ConflictResolution, EvidenceConflict
from .evidence_packet import ProductEvidencePacket
from .lifecycle import ALLOWED_TRANSITIONS, InvalidLifecycleTransition, assert_transition
from .truth import ProductTruth  # noqa: F401

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ConflictResolution",
    "EvidenceConflict",
    "InvalidLifecycleTransition",
    "ProductEvidencePacket",
    "ProductTruth",
    "assert_transition",
]
