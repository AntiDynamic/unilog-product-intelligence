"""Application-controlled retrieval tools; agents cannot perform arbitrary I/O."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from .core import (
    DomainResolver,
    EvidenceExtractor,
    FetchResult,
    ManufacturerProfile,
    ParsedDocument,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourceParser,
    SourceRecord,
    SourceVerifier,
    canonicalize_url,
)


class RetrievalToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    value: object | None = None
    reason: str | None = None


class ManufacturerRetrievalTools:
    """Narrow function surface for controlled manufacturer retrieval."""

    def __init__(
        self,
        resolver: DomainResolver,
        verifier: SourceVerifier,
        fetcher: SourceFetcher,
        extractor: EvidenceExtractor | None = None,
    ) -> None:
        self.resolver = resolver
        self.verifier = verifier
        self.fetcher = fetcher
        self.extractor = extractor

    def get_cached_manufacturer_domain(self, manufacturer_id: str) -> RetrievalToolResult:
        candidates = self.resolver.resolve(manufacturer_id, manufacturer_id)
        return RetrievalToolResult(
            status="hit" if candidates else "miss",
            value=[candidate.model_dump() for candidate in candidates],
        )

    def discover_manufacturer_domain(
        self, manufacturer_id: str, manufacturer_name: str, mpn: str | None = None
    ) -> RetrievalToolResult:
        candidates = self.resolver.resolve(manufacturer_id, manufacturer_name, None)
        return RetrievalToolResult(
            status="candidate" if candidates else "unresolved",
            value=[candidate.model_dump() for candidate in candidates],
        )

    def discover_product_source(
        self, product_id: str, manufacturer_id: str, domain: str, path: str = "/"
    ) -> RetrievalToolResult:
        url = canonicalize_url(domain.rstrip("/") + "/" + path.lstrip("/"))
        return RetrievalToolResult(
            status="candidate",
            value=SourceRecord(
                canonical_url=url,
                original_url=url,
                source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
                decision=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
                manufacturer_id=manufacturer_id,
                manufacturer_domain=domain,
                product_id=product_id,
            ).model_dump(),
        )

    def get_cached_source(self, url: str, refresh: bool = False) -> RetrievalToolResult:
        cached = self.fetcher.cache.get(url, refresh=refresh)
        return RetrievalToolResult(
            status=cached.cache_status.value if cached else "cache_miss",
            value=cached.model_dump() if cached else None,
        )

    def fetch_manufacturer_source(
        self, source: SourceRecord, profile: ManufacturerProfile, refresh: bool = False
    ) -> RetrievalToolResult:
        verified = self.verifier.verify_source(source, profile)
        result = self.fetcher.fetch(verified, refresh=refresh)
        return RetrievalToolResult(
            status=result.source.retrieval_status.value
            if result.source.retrieval_status
            else "blocked",
            value=result.model_dump(),
            reason=result.error,
        )

    def parse_source(self, fetch: FetchResult, parser: SourceParser) -> RetrievalToolResult:
        parsed = parser.parse(fetch)
        return RetrievalToolResult(status="parsed", value=parsed.model_dump())

    def get_source_evidence(
        self, document: ParsedDocument, url: str, product_context: Mapping[str, object]
    ) -> RetrievalToolResult:
        if self.extractor is None:
            return RetrievalToolResult(
                status="unavailable", reason="evidence_extractor_not_configured"
            )
        result = self.extractor.extract(document, url, product_context)
        return RetrievalToolResult(status="extracted", value=result.model_dump())
