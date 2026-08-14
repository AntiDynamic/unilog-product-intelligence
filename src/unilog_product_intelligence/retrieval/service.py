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
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourcePolicy,
    SourceRecord,
    SourceVerifier,
)


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
    search_calls: int = 0
    url_context_calls: int = 0
    evidence_count: int = 0


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
                return product, job
            job.state = ManufacturerJobState.FETCHED
            parsed = self.parser.parse(fetched)
            if not _source_relevant(parsed, terms):
                job.state = ManufacturerJobState.REVIEW_REQUIRED
                job.error = "source_not_relevant_to_product"
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
            job.state = ManufacturerJobState.EVIDENCE_EXTRACTED
            job.evidence_count = len(extracted.candidates)
            product = _attach_source(product, fetched.source)
            product = self._attach_candidates(product, extracted.candidates)
            job.state = ManufacturerJobState.COMPLETED
            return product, job
        except (RuntimeError, ValueError) as error:
            job.state = ManufacturerJobState.FAILED
            job.error = type(error).__name__
            return product, job

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
