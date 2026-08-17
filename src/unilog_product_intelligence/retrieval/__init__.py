"""Phase 5 manufacturer-source retrieval and evidence primitives."""

from .agents import DiscoveryResult, ManufacturerDiscoveryAgent
from .core import (
    DocumentLink,
    DomainResolver,
    EvidenceCandidate,
    EvidenceExtractor,
    EvidenceSelector,
    HtmlParser,
    ManufacturerProfile,
    ParsedDocument,
    Phase5FailureReason,
    SafeNetworkTargetResolver,
    SourceCache,
    SourceFetcher,
    SourcePolicy,
    SourceRecord,
    SourceVerifier,
    canonicalize_url,
)
from .mpn_normalizer import MpnHypothesis, MpnHypothesisType, MpnNormalizer
from .service import ManufacturerIntelligenceService
from .source_discovery import (
    DeterministicUrlStrategy,
    MpnMatchClassification,
    ProductIdentityMatch,
    ProductIdentityMatcher,
    ProductSourceCandidate,
    ProductSourceDiscoveryService,
)

__all__ = [
    "DeterministicUrlStrategy",
    "DomainResolver",
    "DocumentLink",
    "EvidenceSelector",
    "EvidenceCandidate",
    "EvidenceExtractor",
    "HtmlParser",
    "ManufacturerIntelligenceService",
    "ManufacturerProfile",
    "MpnHypothesis",
    "MpnHypothesisType",
    "MpnMatchClassification",
    "MpnNormalizer",
    "ParsedDocument",
    "Phase5FailureReason",
    "SafeNetworkTargetResolver",
    "SourceCache",
    "SourceFetcher",
    "SourcePolicy",
    "SourceRecord",
    "SourceVerifier",
    "canonicalize_url",
    "DiscoveryResult",
    "ManufacturerDiscoveryAgent",
    "ProductIdentityMatch",
    "ProductIdentityMatcher",
    "ProductSourceCandidate",
    "ProductSourceDiscoveryService",
]
