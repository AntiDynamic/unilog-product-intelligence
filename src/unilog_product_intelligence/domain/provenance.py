"""Provenance and final attribute value models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.domain.truth import SourceAuthority


class ProvenanceKind(StrEnum):
    """Origin classification for a final attribute value."""

    EXTRACTED_HTML = "extracted_html"
    EXTRACTED_PDF = "extracted_pdf"
    MODEL_INFERRED = "model_inferred"
    DEFAULT_RULE = "default_rule"
    UNVERIFIED_SOURCE = "unverified_source"


class FinalAttribute(BaseModel):
    """An enriched, validated final attribute with full provenance lineage.

    Design: frozen=True + extra="forbid" for immutability.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    attribute: str = Field(description="Canonical attribute name")
    value: Any = Field(description="Final normalized attribute value")
    uom: str | None = Field(default=None, description="Unit of measure if applicable")
    provenance_kind: ProvenanceKind = Field(
        default=ProvenanceKind.EXTRACTED_HTML,
        description="Source channel / method that produced this value",
    )
    evidence_id: str | None = Field(
        default=None,
        description="ID of the EvidenceReference grounding this value",
    )
    source_url: str | None = Field(
        default=None,
        description="Canonical URL of the source page or document",
    )
    source_authority: SourceAuthority | None = Field(
        default=None,
        description="Authority tier of the source",
    )


__all__ = ["FinalAttribute", "ProvenanceKind"]
