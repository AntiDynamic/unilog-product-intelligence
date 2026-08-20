"""Deeply immutable value types for the ProductEvidencePacket.

These replace bare `dict[str, Any]` and `str` fields with proper domain models
so that every nested value inside a ProductEvidencePacket is also immutable.

Design:
  - All models are frozen=True, extra="forbid"
  - All collection fields use `tuple` (never `list`)
  - No circular imports — this module depends only on stdlib types
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# ── Backward-compatibility re-exports ─────────────────────────────────────────
# The pre-existing domain/models.py re-exported these names from domain.truth so
# that test files and production code that already import from `domain.models`
# continue to work without modification.
from unilog_product_intelligence.domain.truth import (
    ProductIdentity as ProductIdentity,  # noqa: F401
    ProductTruth as ProductTruth,  # noqa: F401
    Source as Source,  # noqa: F401
    SourceAuthority as SourceAuthority,  # noqa: F401
    SourceStatus as SourceStatus,  # noqa: F401
    SourceType as SourceType,  # noqa: F401
)

__all__ = [
    # New domain models for deep immutability
    "DiscoveredAsset",
    "FeatureEvidence",
    "StructuredSpec",
    # Backward-compat re-exports from domain.truth
    "ProductIdentity",
    "ProductTruth",
    "Source",
    "SourceAuthority",
    "SourceStatus",
    "SourceType",
]



class StructuredSpec(BaseModel):
    """A single key-value specification extracted from a manufacturer page.

    Maps one row in a product spec table: attribute -> value (+ optional unit).

    The optional ``evidence_id`` links back to the ``EvidenceReference`` that
    yielded this spec, enabling the full chain:
        spec -> EvidenceReference -> VerifiedProductSourceContext -> source URL
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    attribute: str
    raw_value: str
    unit: str | None = None
    # Back-reference to the EvidenceReference that produced this spec.
    # None when the spec comes from deterministic HTML parsing before evidence
    # IDs are assigned (e.g. VerifiedProductSourceContext.structured_facts).
    evidence_id: str | None = None


class FeatureEvidence(BaseModel):
    """A single feature/bullet-point from a manufacturer page.

    Replaces bare ``str`` in ``ProductEvidencePacket.features`` so that each
    feature can be linked back to the evidence record that supports it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    # Optional normalised/cleaned form of the feature text.
    value: str | None = None
    # Zero or more evidence IDs that support this feature.
    evidence_ids: tuple[str, ...] = ()


class DiscoveredAsset(BaseModel):
    """A discovered digital asset (document or image) from a manufacturer source.

    Carries enough metadata to distinguish document type, link back to evidence,
    and display to the end user without requiring a round-trip to the source.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    # "document" | "image" | "video" | "unknown"
    asset_type: str
    # Optional back-reference to the EvidenceReference that surfaced this asset.
    evidence_id: str | None = None
