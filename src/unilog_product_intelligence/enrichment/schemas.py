"""Flat Gemini structured output schemas for Phase 6 enrichment.

Defines the clean, flat response envelopes expected from Gemini models during
attribute extraction. Designed specifically to avoid deep nesting issues with
Gemini 2.5 structured output.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GeminiAttributeCandidate(BaseModel):
    """Flat candidate schema for an extracted attribute from verified evidence."""

    model_config = ConfigDict(extra="ignore")

    attribute: str = Field(description="Canonical attribute name being extracted")
    value: Any = Field(description="Extracted attribute value as string or number")
    uom: str | None = Field(default=None, description="Extracted unit of measure, if applicable")
    evidence_id: str = Field(description="Exact ID of the evidence snippet grounding this value")
    evidence_text: str | None = Field(
        default=None, description="Verbatim quote from source grounding the value"
    )
    normalized_value: str | None = Field(
        default=None, description="Normalized representation of the value"
    )
    status: str = Field(
        default="direct",
        description="Evidence directness: direct, table, figure, calculated, inferred",
    )
    reason: str = Field(
        default="Source-backed candidate.",
        description="Brief grounding rationale citing the evidence",
    )


class GeminiEnrichmentResponse(BaseModel):
    """Flat response envelope for Gemini enrichment requests."""

    model_config = ConfigDict(extra="ignore")

    candidates: list[GeminiAttributeCandidate] = Field(
        default_factory=list,
        description="List of extracted attribute candidates grounded in provided evidence",
    )
    unresolved_attributes: list[str] = Field(
        default_factory=list,
        description="List of planned attribute names that could not be grounded in evidence",
    )


__all__ = [
    "GeminiAttributeCandidate",
    "GeminiEnrichmentResponse",
]
