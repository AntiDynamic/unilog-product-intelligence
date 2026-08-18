"""Structured object encapsulating verified manufacturer source content."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.enrichment.models import EvidenceReference


class VerifiedProductSourceContext(BaseModel):
    """Bounded, structured container for parsed source text, facts, and evidence references."""

    model_config = ConfigDict(extra="forbid")

    product_id: str
    manufacturer: str | None = None
    brand: str | None = None
    mpn: str | None = None

    canonical_product_url: str
    source_id: str
    source_authority: str  # e.g. "AUTHORITATIVE" or "SECONDARY"
    source_type: str       # e.g. "MANUFACTURER_PAGE" or "AUTHORIZED_DISTRIBUTOR"

    page_title: str | None = None
    page_description: str | None = None
    page_text: str = ""    # Bounded clean textual representation (specs, features, descriptions)

    structured_facts: list[dict[str, Any]] = Field(default_factory=list)  # Extracted spec pairs
    source_chunks: list[dict[str, Any]] = Field(default_factory=list)     # Section/page chunks
    evidence_references: list[EvidenceReference] = Field(default_factory=list)

    image_urls: list[str] = Field(default_factory=list)
    document_urls: list[str] = Field(default_factory=list)

    def build_prompt_context(self) -> str:
        """Format a clean, bounded multi-layer prompt section for Gemini."""
        parts: list[str] = []
        if self.page_title:
            parts.append(f"PAGE TITLE: {self.page_title}")
        if self.page_description:
            parts.append(f"PAGE DESCRIPTION: {self.page_description}")

        if self.structured_facts:
            facts_lines = [
                f"  - {fact.get('attribute', '')}: {fact.get('raw_value', '')}"
                for fact in self.structured_facts[:30]
                if fact.get("attribute") and fact.get("raw_value")
            ]
            if facts_lines:
                parts.append("DETERMINISTIC STRUCTURED SPECS:\n" + "\n".join(facts_lines))

        if self.page_text:
            parts.append(f"CLEAN SOURCE CONTENT:\n{self.page_text[:4000]}")

        return "\n\n".join(parts)


__all__ = ["VerifiedProductSourceContext"]
