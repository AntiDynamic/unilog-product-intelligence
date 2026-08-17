"""Manufacturer intelligence workflow: verify, fetch, parse, extract, attach provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.truth import (
    AssessmentMetadata,
    CandidateValue,
    Conflict,
    ConflictType,
    Evidence,
    EvidenceType,
    ProductTruth,
    Source,
    SourceAuthority,
    SourceStatus,
    SourceType,
    ValueStatus,
)

from .core import (
    CacheStatus,
    EvidenceCandidate,
    EvidenceExtractor,
    EvidenceStatus,
    HtmlParser,
    ManufacturerProfile,
    Phase5FailureReason,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourcePolicy,
    SourceRecord,
    SourceVerifier,
)
from .source_discovery import ProductIdentityMatcher, ProductSourceDiscoveryService


class ManufacturerJobState(StrEnum):
    RECEIVED = "received"
    DOMAIN_RESOLVED = "domain_resolved"
    SOURCE_VERIFIED = "source_verified"
    FETCHED = "fetched"
    PARSED = "parsed"
    EVIDENCE_EXTRACTED = "evidence_extracted"
    COMPLETED = "completed"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


class ManufacturerJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(default_factory=lambda: "manufacturer-job-" + str(uuid4()))
    product_id: str
    state: ManufacturerJobState = ManufacturerJobState.RECEIVED
    cache_status: CacheStatus | None = None
    source_id: str | None = None
    error: str | None = None
    failure_reason: Phase5FailureReason | None = None
    search_calls: int = 0
    url_context_calls: int = 0
    url_context_result_count: int = 0
    url_context_urls: tuple[str, ...] = ()
    evidence_count: int = 0
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    request_id: str | None = None
    estimated_cost_usd: float | None = None


class ManufacturerIntelligenceService:
    """One bounded source workflow. It never performs broad crawling or final enrichment."""

    def __init__(
        self,
        fetcher: SourceFetcher,
        verifier: SourceVerifier | None = None,
        parser: HtmlParser | None = None,
        extractor: EvidenceExtractor | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.verifier = verifier or SourceVerifier(SourcePolicy())
        self.parser = parser or HtmlParser()
        self.extractor = extractor
        self._service = ProductTruthService()

    def process(
        self,
        product: ProductTruth,
        source: SourceRecord,
        profile: ManufacturerProfile,
        refresh: bool = False,
    ) -> tuple[ProductTruth, ManufacturerJob]:
        job = ManufacturerJob(product_id=product.product_id, source_id=source.source_id)
        try:
            terms = _product_terms(product)
            verified = self.verifier.verify_source(source, profile, terms)
            if verified.decision != SourceDecision.VERIFIED_MANUFACTURER_SOURCE:
                job.state = ManufacturerJobState.REVIEW_REQUIRED
                job.error = verified.decision.value
                job.failure_reason = Phase5FailureReason.DOMAIN_UNVERIFIED
                return product, job
            job.state = ManufacturerJobState.SOURCE_VERIFIED
            fetched = self.fetcher.fetch(verified, refresh=refresh)
            job.cache_status = fetched.cache_status
            if (
                fetched.source.retrieval_status is not None
                and fetched.source.retrieval_status.value != "success"
            ):
                job.state = ManufacturerJobState.FAILED
                job.error = fetched.error or fetched.source.retrieval_status.value
                job.failure_reason = Phase5FailureReason.SOURCE_FETCH_FAILED
                return product, job
            job.state = ManufacturerJobState.FETCHED
            parsed = self.parser.parse(fetched)
            identity = ProductIdentityMatcher().match(product, parsed)
            if identity.identity_score < 0.6:
                job.state = ManufacturerJobState.REVIEW_REQUIRED
                job.error = f"source_not_relevant_to_product:{identity.classification}"
                job.failure_reason = Phase5FailureReason.PRODUCT_IDENTITY_MISMATCH
                return product, job
            job.state = ManufacturerJobState.PARSED
            if self.extractor is None:
                job.state = ManufacturerJobState.COMPLETED
                return _attach_source(product, fetched.source), job
            extracted = self.extractor.extract(
                parsed,
                fetched.source.canonical_url,
                {
                    field.field_name: product.raw_value(field.field_name)
                    for field in product.raw_inputs
                },
            )
            response = self.extractor.last_response
            if response is not None:
                job.url_context_calls = response.url_context_call_count
                job.url_context_result_count = response.url_context_result_count
                job.url_context_urls = response.url_context_urls
                job.model = response.model
                job.input_tokens = response.input_tokens
                job.output_tokens = response.output_tokens
                job.cached_tokens = response.cached_tokens
                job.total_tokens = response.total_tokens
                job.latency_ms = response.latency_ms
                job.request_id = response.request_id
                job.estimated_cost_usd = response.estimated_cost_usd
            job.state = ManufacturerJobState.EVIDENCE_EXTRACTED
            job.evidence_count = len(extracted.candidates)
            if not extracted.candidates:
                job.failure_reason = Phase5FailureReason.NO_AUTHORITATIVE_EVIDENCE
            product = _attach_source(product, fetched.source)
            product = self._attach_candidates(product, extracted.candidates)
            job.state = ManufacturerJobState.COMPLETED
            return product, job
        except (RuntimeError, ValueError) as error:
            job.state = ManufacturerJobState.FAILED
            job.error = type(error).__name__
            if job.failure_reason is None:
                job.failure_reason = Phase5FailureReason.SOURCE_FETCH_FAILED
            return product, job

    def recover(
        self,
        product: ProductTruth,
        profile: ManufacturerProfile,
        failed_job: ManufacturerJob,
        candidate_urls: tuple[str, ...] = (),
    ) -> tuple[ProductTruth, ManufacturerJob]:
        """Attempt adaptive recovery when the primary source URL failed.

        This method tries alternate candidate URLs produced by
        ProductSourceDiscoveryService using the same SourceFetcher, SourceVerifier,
        and ProductIdentityMatcher as the normal path.  No validation is bypassed.

        Covers the following failure cases:
          * SOURCE_FETCH_FAILED  — original URL returned 4xx/5xx or timed out.
          * PRODUCT_IDENTITY_MISMATCH — page loaded but MPN/manufacturer not found.
          * PRODUCT_SOURCE_NOT_FOUND  — no candidate matched on first attempt.

        A repair is only accepted if the replacement source passes the same identity
        and source-verification checks as the primary path.
        """
        recoverable = {
            Phase5FailureReason.SOURCE_FETCH_FAILED,
            Phase5FailureReason.PRODUCT_IDENTITY_MISMATCH,
            Phase5FailureReason.PRODUCT_SOURCE_NOT_FOUND,
        }
        if failed_job.failure_reason not in recoverable:
            return product, failed_job
        if not candidate_urls and not profile.verified_domains:
            return product, failed_job
        discovery = ProductSourceDiscoveryService(self.fetcher)
        found = discovery.discover(product, profile, candidate_urls=candidate_urls)
        if not found:
            recovery_job = failed_job.model_copy(
                update={
                    "state": ManufacturerJobState.REVIEW_REQUIRED,
                    "error": "recovery_no_candidates_passed",
                    "failure_reason": Phase5FailureReason.PRODUCT_SOURCE_NOT_FOUND,
                }
            )
            return product, recovery_job
        best = found[0]
        recovery_source = SourceRecord(
            canonical_url=best.url,
            original_url=best.url,
            source_kind=best.source_kind,
            decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
            manufacturer_id=profile.manufacturer_id,
            manufacturer_domain=_host_of(best.url),
            product_id=product.product_id,
        )
        return self.process(product, recovery_source, profile)

    def _attach_candidates(
        self, product: ProductTruth, candidates: list[EvidenceCandidate]
    ) -> ProductTruth:
        for evidence_candidate in candidates:
            if evidence_candidate.status in {EvidenceStatus.UNRESOLVED, EvidenceStatus.INFERRED}:
                candidate_status = ValueStatus.INFERRED
            else:
                candidate_status = ValueStatus.CANDIDATE
            attribute_id = "attribute-" + "-".join(evidence_candidate.attribute.casefold().split())
            candidate_id = evidence_candidate.candidate_id
            candidate = CandidateValue(
                candidate_id=candidate_id,
                raw_value=evidence_candidate.raw_value,
                normalized_value=evidence_candidate.normalized_candidate,
                uom=evidence_candidate.unit,
                status=candidate_status,
                source_ids=[evidence_candidate.source_id],
                assessment=AssessmentMetadata(
                    source_authority=SourceAuthority.AUTHORITATIVE, evidence_available=True
                ),
            )
            try:
                product = self._service.add_attribute_candidate(
                    product, attribute_id, candidate, evidence_candidate.attribute
                )
            except ValueError:
                continue
            evidence = Evidence(
                evidence_id="evidence-" + str(uuid4()),
                source_id=evidence_candidate.source_id,
                product_id=product.product_id,
                attribute_id=attribute_id,
                candidate_id=candidate_id,
                quoted_text=evidence_candidate.source_text,
                document_page=evidence_candidate.page,
                location=evidence_candidate.location,
                extracted_at=datetime.now(UTC),
                evidence_type=_evidence_type(evidence_candidate.evidence_type),
            )
            product = self._service.attach_evidence(product, evidence)
            product = _preserve_conflict(product, attribute_id, candidate_id)
        return product


def _attach_source(product: ProductTruth, source: SourceRecord) -> ProductTruth:
    result = product.model_copy(deep=True)
    if any(item.source_id == source.source_id for item in result.sources):
        return result
    result.sources.append(
        Source(
            source_id=source.source_id,
            source_type=SourceType.MANUFACTURER_PAGE
            if source.source_kind == SourceKind.MANUFACTURER_PRODUCT_PAGE
            else SourceType.MANUFACTURER_DOCUMENT,
            authority=SourceAuthority.AUTHORITATIVE,
            uri=source.canonical_url,
            manufacturer_id=source.manufacturer_id,
            retrieved_at=source.fetched_at,
            content_hash=source.content_hash,
            status=SourceStatus.AVAILABLE,
            metadata={
                "source_kind": source.source_kind.value,
                "retrieval_method": source.retrieval_method,
            },
        )
    )
    return result


def _preserve_conflict(product: ProductTruth, attribute_id: str, candidate_id: str) -> ProductTruth:
    attribute = product.attribute(attribute_id)
    normalized = {
        candidate.normalized_value
        for candidate in attribute.candidates
        if candidate.normalized_value is not None
    }
    if len(normalized) < 2:
        return product
    ids = [candidate.candidate_id for candidate in attribute.candidates]
    if any(set(conflict.candidate_ids) == set(ids) for conflict in product.conflicts):
        return product
    return ProductTruthService().create_conflict(
        product,
        Conflict(
            conflict_id="conflict-" + str(uuid4()),
            product_id=product.product_id,
            attribute_id=attribute_id,
            candidate_ids=ids,
            source_ids=attribute.source_ids,
            conflict_type=ConflictType.VALUE_DISAGREEMENT,
        ),
    )


def _product_terms(product: ProductTruth) -> tuple[str, ...]:
    values = [
        str(product.raw_value(name) or "")
        for name in ("Mfg_Part_Num", "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand")
    ]
    return tuple(value for value in values if value.strip())


def _evidence_type(status: EvidenceStatus) -> EvidenceType:
    return {
        EvidenceStatus.TABLE: EvidenceType.TABLE_CELL,
        EvidenceStatus.FIGURE: EvidenceType.IMAGE_REGION,
        EvidenceStatus.CALCULATED: EvidenceType.CALCULATED,
        EvidenceStatus.INFERRED: EvidenceType.MODEL_INFERENCE,
    }.get(status, EvidenceType.DIRECT_TEXT)


def _source_relevant(document: object, terms: tuple[str, ...]) -> bool:
    chunks = getattr(document, "chunks", [])
    text = " ".join(getattr(chunk, "text", "") for chunk in chunks).casefold()
    meaningful = tuple(term.casefold().strip() for term in terms if len(term.strip()) >= 3)
    return bool(meaningful) and any(term in text for term in meaningful)


def _host_of(url: str) -> str:
    """Return the netloc (host) of a URL for use as manufacturer_domain."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.netloc or url

