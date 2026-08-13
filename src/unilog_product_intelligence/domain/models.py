"""Canonical domain types for evidence-constrained product intelligence.

Phase 0 defines the boundary and typed vocabulary. Enrichment behavior is intentionally
left for later phases; no model-generated product values are created here.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Evidence(BaseModel):
    """A traceable source reference supporting a candidate or accepted fact."""

    model_config = ConfigDict(extra="forbid")

    source_url: HttpUrl | None = None
    source_name: str | None = None
    excerpt: str | None = None
    source_type: Literal["input", "manufacturer", "unilog_master", "ai_candidate"]
    retrieved_at: datetime | None = None


class AttributeFact(BaseModel):
    """A typed-enough placeholder for a future normalized product attribute."""

    model_config = ConfigDict(extra="forbid")

    label: str
    value: str | None = None
    uom: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)
    is_candidate: bool = False


class ProductIdentity(BaseModel):
    """Identity fields originating from supplied or approved sources."""

    model_config = ConfigDict(extra="forbid")

    manufacturer_part_number: str | None = None
    manufacturer: str | None = None
    brand: str | None = None
    source_record_id: str | None = None


class ProductTruth(BaseModel):
    """Canonical product truth boundary used by all future renderers and delivery."""

    model_config = ConfigDict(extra="forbid")

    identity: ProductIdentity
    category: str | None = None
    classification_path: list[str] = Field(default_factory=list)
    attributes: list[AttributeFact] = Field(default_factory=list)
    sources: list[Evidence] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    validation_results: list[str] = Field(default_factory=list)
    descriptions: dict[str, str] = Field(default_factory=dict)
    provenance: list[str] = Field(default_factory=list)
