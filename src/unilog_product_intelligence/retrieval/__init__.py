"""Phase 5 manufacturer-source retrieval and evidence primitives."""

from .agents import DiscoveryResult, ManufacturerDiscoveryAgent
from .core import (
    DomainResolver,
    EvidenceCandidate,
    EvidenceExtractor,
    HtmlParser,
    ManufacturerProfile,
    ParsedDocument,
    SourceCache,
    SourceFetcher,
    SourcePolicy,
    SourceRecord,
    SourceVerifier,
    canonicalize_url,
)
from .service import ManufacturerIntelligenceService

__all__ = [
    "DomainResolver",
    "EvidenceCandidate",
    "EvidenceExtractor",
    "HtmlParser",
    "ManufacturerIntelligenceService",
    "ManufacturerProfile",
    "ParsedDocument",
    "SourceCache",
    "SourceFetcher",
    "SourcePolicy",
    "SourceRecord",
    "SourceVerifier",
    "canonicalize_url",
    "DiscoveryResult",
    "ManufacturerDiscoveryAgent",
]
