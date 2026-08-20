"""Flat Gemini structured output schemas for Phase 6 enrichment.

Defines the clean, flat response envelopes expected from Gemini models during
attribute extraction. Designed specifically to avoid deep nesting issues with
Gemini 2.5 structured output.

Key types
---------
``AttributeProposal``      — The canonical, frozen proposal model.  Every attribute
                             value proposed by Gemini must carry evidence_ids that
                             point to real EvidenceReference records in the packet.
                             Used by EvidenceConstraintValidator to enforce this.

``GeminiAttributeCandidate`` — Alias for AttributeProposal for backward compatibility.
                             Existing references to GeminiAttributeCandidate continue
                             to work unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AttributeProposal(BaseModel):
    """A single attribute value proposed by Gemini, grounded in evidence.

    Every proposal must cite at least one evidence_id from the packet.
    Proposals with missing or unknown evidence IDs are rejected by
    EvidenceConstraintValidator before they can reach ProductTruth.

    Design: frozen=True + extra="forbid" — immutable value object.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    attribute: str = Field(description="Canonical attribute name being proposed")
    value: str | None = Field(default=None, description="Proposed attribute value as a string")
    uom: str | None = Field(default=None, description="Extracted unit of measure, if applicable")
    # One or more evidence IDs from the packet that ground this proposal.
    # Must reference real EvidenceReference.evidence_id values — never invented IDs.
    evidence_ids: tuple[str, ...] = Field(
        default=(),
        description="Exact IDs of evidence records from the packet grounding this value",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence [0.0, 1.0]",
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief grounding rationale citing the evidence",
    )


# Backward-compatibility alias — existing code that imports GeminiAttributeCandidate
# continues to work without modification.  New code should use AttributeProposal.
GeminiAttributeCandidate = AttributeProposal


class GeminiEnrichmentResponse(BaseModel):
    """Flat response envelope for Gemini enrichment requests."""

    model_config = ConfigDict(extra="ignore")

    proposals: tuple[AttributeProposal, ...] = Field(
        default=(),
        description="Attribute proposals grounded in provided evidence",
    )
    # Keep the old `candidates` field as a synonym so that any deserialized
    # responses from the existing model still parse correctly.
    candidates: list[AttributeProposal] = Field(
        default_factory=list,
        description="Legacy alias for proposals (use proposals in new code)",
    )
    unresolved_attributes: list[str] = Field(
        default_factory=list,
        description="Planned attribute names that could not be grounded in evidence",
    )


__all__ = [
    "AttributeProposal",
    "GeminiAttributeCandidate",
    "GeminiEnrichmentResponse",
]
