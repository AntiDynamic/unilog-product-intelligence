"""Domain-level evidence conflict model.

EvidenceConflict is a pure value object describing a disagreement between
evidence candidates for the same attribute.  It lives in the domain layer so
it can be referenced by ProductEvidencePacket (also in the domain layer)
without creating a cross-layer circular import.

The ConflictEngine (the logic that detects and resolves conflicts) lives in
enrichment/conflicts.py and imports from here.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.domain.truth import SourceAuthority


class ConflictResolution(StrEnum):
    """How a detected conflict should be handled."""

    AUTHORITATIVE_SOURCE_WINS = "authoritative_source_wins"
    """The higher-authority source value is accepted automatically."""

    REVIEW_REQUIRED = "review_required"
    """Authorities are equal or ambiguous — a human must decide."""

    ESCALATE_TO_STRONG_MODEL = "escalate_to_strong_model"
    """Both sources have equal authority (e.g. OEM page vs OEM PDF) and disagree;
    send to the stronger Gemini model for a reasoned resolution attempt."""


class EvidenceConflict(BaseModel):
    """Immutable record of a value disagreement detected by ConflictEngine.

    Attributes
    ----------
    attribute:
        The canonical attribute name (e.g. ``"voltage"``).
    values:
        The disagreeing values in discovery order.
    evidence_ids:
        Corresponding EvidenceReference evidence_ids (parallel to ``values``).
    source_authorities:
        The SourceAuthority of each evidence source (parallel to ``values``).
    recommended_value:
        Set when ConflictEngine can resolve deterministically via authority ranking;
        ``None`` when the conflict is REVIEW_REQUIRED or ESCALATE_TO_STRONG_MODEL.
    recommended_evidence_id:
        The evidence_id of the recommended value (``None`` when unresolved).
    resolution:
        The ConflictResolution decision produced by ConflictEngine.resolve().
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    attribute: str
    values: tuple[str, ...] = Field(min_length=2)
    evidence_ids: tuple[str, ...] = Field(min_length=2)
    source_authorities: tuple[SourceAuthority, ...] = ()

    recommended_value: str | None = None
    recommended_evidence_id: str | None = None

    resolution: ConflictResolution = ConflictResolution.REVIEW_REQUIRED


__all__ = ["ConflictResolution", "EvidenceConflict"]
