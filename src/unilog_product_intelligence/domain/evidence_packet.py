"""Canonical ProductEvidencePacket: the shared evidence object crossing Phase 5 → 6 → Delivery.

This is the single source-of-truth for all evidence that enrichment and delivery need.
It is assembled once inside ManufacturerIntelligenceService.process() and flows unmodified
through Phase65Pipeline → EnrichmentService → Phase65ResultDeliveryAdapter.

Design principles:
  - frozen=True  — value object, never mutated after construction
  - All nested fields use immutable domain models (StructuredSpec, FeatureEvidence) or
    plain scalars (str, float) — never bare dict[str, Any] or list.
  - Never contains raw HTML.  Only structured, bounded representations.
  - EvidenceConflict is imported lazily from domain.conflicts to avoid circular imports.

Immutability guarantee
----------------------
  frozen=True protects Pydantic model fields from re-assignment.
  tuple (never list) protects collection fields from append/pop mutation.
  StructuredSpec and FeatureEvidence are themselves frozen=True models, so nested
  objects are also immutable.  This enforces the invariant:

    Phase 5 creates packet
          ↓
    Phase 6 receives exact same truth
          ↓
    Delivery receives exact same truth

  No stage can quietly mutate the packet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.domain.models import FeatureEvidence, StructuredSpec
from unilog_product_intelligence.domain.truth import SourceAuthority

if TYPE_CHECKING:
    # Imported only for type annotations — real import lives in domain.conflicts
    from unilog_product_intelligence.domain.conflicts import EvidenceConflict


class ProductEvidencePacket(BaseModel):
    """Bounded, deeply immutable evidence value object produced by Phase 5.

    Carries everything enrichment and delivery need from the verified manufacturer source:
    identity, evidence references, structured facts, features, and asset URLs.

    The packet replaces the previous pattern of passing product, plans, evidence, and
    source_context as separate arguments — all of that information is now in one place.

    Lifecycle
    ---------
    Built by  : ManufacturerIntelligenceService.process()
    Stored on : ManufacturerJob.evidence_packet
    Exposed on: Phase65Result.evidence_packet
    Consumed by: EnrichmentService.enrich(), Phase65ResultDeliveryAdapter.to_record()
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    # ── Identity ──────────────────────────────────────────────────────────────
    product_id: str
    mpn: str | None = None
    manufacturer: str | None = None
    brand: str | None = None

    # ── Source references ─────────────────────────────────────────────────────
    # canonical_product_url duplicates source_context.canonical_product_url for
    # convenience — callers should not need to navigate into source_context just
    # to get the URL.
    canonical_product_url: str | None = None

    # Flat structured representation of the verified source page.
    # Kept as a nested object (VerifiedProductSourceContext) for prompt building.
    # Avoid importing VerifiedProductSourceContext directly here to keep the domain
    # layer clean; type is Any with runtime isinstance checks where needed.
    source_context: Any = None  # VerifiedProductSourceContext | None

    # ── Evidence ──────────────────────────────────────────────────────────────
    # The authoritative list of EvidenceReference objects for Gemini enrichment.
    # Same type as already used by EvidenceGroundedEnrichmentAgent.
    # Stored as tuple for immutability; the agent converts to tuple[EvidenceReference,...].
    evidence: tuple[Any, ...] = ()  # tuple[EvidenceReference, ...]

    # ── Structured knowledge from the primary source page ─────────────────────
    # Direct spec key-value pairs extracted by HtmlProductEvidenceExtractor.
    # Each StructuredSpec has: attribute (str), raw_value (str), unit (str | None),
    # evidence_id (str | None).  Replaces bare dict[str, Any] for deep immutability.
    structured_facts: tuple[StructuredSpec, ...] = ()

    # Feature/bullet list from the manufacturer page (ordered, bounded to 20).
    # Each FeatureEvidence has: name (str), value (str | None), evidence_ids (tuple[str,...]).
    # Replaces bare tuple[str, ...] so each feature can cite its evidence.
    features: tuple[FeatureEvidence, ...] = ()

    # ── Asset URLs discovered from the primary source ─────────────────────────
    # Document URLs (PDFs, spec sheets, manuals, etc.) ranked by relevance.
    document_urls: tuple[str, ...] = ()

    # Image URLs (gallery, primary, alternates).
    image_urls: tuple[str, ...] = ()

    # ── Source quality signals ────────────────────────────────────────────────
    source_authority: SourceAuthority | None = None
    identity_score: float | None = None

    # ── Evidence conflicts detected by ConflictEngine (Stage 6) ──────────────
    # Populated lazily after enrichment; empty at Phase 5 boundary.
    conflicts: tuple[Any, ...] = Field(default=(), repr=False)
    # tuple[EvidenceConflict, ...] — typed as Any to avoid circular imports


__all__ = ["ProductEvidencePacket"]
