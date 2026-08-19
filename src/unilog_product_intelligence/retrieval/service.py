"""Manufacturer intelligence workflow: verify, fetch, parse, extract, attach provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.source_context import VerifiedProductSourceContext
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
from unilog_product_intelligence.enrichment.agent import evidence_references

from .core import (
    AsyncSourceFetcher,
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
from .digital_assets import DigitalAssetDiscoveryService
from .html_extractor import ExtractedProductData, HtmlProductEvidenceExtractor
from .source_discovery import ProductIdentityMatcher, ProductSourceDiscoveryService


class ManufacturerJobState(StrEnum):
    RECEIVED = "received"
    DOMAIN_RESOLVED = "domain_resolved"
    SOURCE_VERIFIED = "source_verified"
    FETCHED = "fetched"
    IDENTITY_VERIFIED = "identity_verified"
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
    source_authority: SourceAuthority = SourceAuthority.UNKNOWN
    source_status: SourceStatus = SourceStatus.UNAVAILABLE
    source_is_product_verified: bool = False
    secondary_source_used: bool = False
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

    identity_score: float | None = None
    mpn_match_type: str | None = None
    raw_mpn_match: bool | None = None
    transformed_mpn_match: bool | None = None
    identity_rejection_reason: str | None = None

    verified_domains_available: tuple[str, ...] = ()
    domains_attempted: tuple[str, ...] = ()
    selected_domain: str | None = None
    domain_attempt_failure_reasons: dict[str, str] = Field(default_factory=dict)

    asset_discovery_status: str | None = None
    asset_discovery_error: str | None = None
    assets_discovered_count: int = 0
    verified_source_context: VerifiedProductSourceContext | None = None


class ManufacturerIntelligenceService:
    """One bounded source workflow. It never performs broad crawling or final enrichment."""

    def __init__(
        self,
        fetcher: SourceFetcher | AsyncSourceFetcher,
        verifier: SourceVerifier | None = None,
        parser: HtmlParser | None = None,
        extractor: EvidenceExtractor | None = None,
        asset_discovery: DigitalAssetDiscoveryService | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.verifier = verifier or SourceVerifier(SourcePolicy())
        self.parser = parser or HtmlParser()
        self.extractor = extractor
        self.asset_discovery = asset_discovery or DigitalAssetDiscoveryService()
        self._service = ProductTruthService()

    def process(
        self,
        product: ProductTruth,
        source: SourceRecord,
        profile: ManufacturerProfile,
        refresh: bool = False,
    ) -> tuple[ProductTruth, ManufacturerJob]:
        is_secondary = source.decision == SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE
        job = ManufacturerJob(
            product_id=product.product_id,
            source_id=source.source_id,
            source_authority=(
                SourceAuthority.SECONDARY if is_secondary else SourceAuthority.AUTHORITATIVE
            ),
            secondary_source_used=is_secondary,
            verified_domains_available=profile.verified_domains,
            domains_attempted=(_host_of(source.canonical_url),),
            selected_domain=_host_of(source.canonical_url),
        )
        try:
            terms = _product_terms(product)
            if is_secondary:
                verified = self.verifier.verify_secondary_source(source, profile, terms)
                if verified.decision != SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE:
                    job.state = ManufacturerJobState.REVIEW_REQUIRED
                    job.error = verified.decision.value
                    job.failure_reason = Phase5FailureReason.DOMAIN_UNVERIFIED
                    return product, job
            else:
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
                job.source_status = SourceStatus.UNAVAILABLE
                return product, job
            job.source_status = SourceStatus.AVAILABLE
            job.state = ManufacturerJobState.FETCHED
            parsed = self.parser.parse(fetched)
            identity = ProductIdentityMatcher().match(product, parsed)
            job.identity_score = identity.identity_score
            job.mpn_match_type = identity.mpn_match_type.value
            job.raw_mpn_match = identity.raw_mpn_match
            job.transformed_mpn_match = identity.transformed_mpn_match
            job.identity_rejection_reason = identity.rejection_reason
            if identity.identity_score < 0.6 or not identity.matched_mpn:
                job.state = ManufacturerJobState.REVIEW_REQUIRED
                job.error = f"source_not_relevant_to_product:{identity.classification}"
                job.failure_reason = Phase5FailureReason.PRODUCT_IDENTITY_MISMATCH
                job.source_is_product_verified = False
                return product, job
            job.source_is_product_verified = True
            job.state = ManufacturerJobState.IDENTITY_VERIFIED
            product = _attach_source(product, fetched.source)

            # Parse HTML structure via HtmlProductEvidenceExtractor
            html_text = fetched.body.decode("utf-8", errors="replace")
            html_data = HtmlProductEvidenceExtractor().extract(
                html_text, base_url=fetched.source.canonical_url
            )

            # Extract evidence candidates
            candidates: list[EvidenceCandidate] = []
            if self.extractor is not None:
                extracted = self.extractor.extract(
                    parsed,
                    fetched.source.canonical_url,
                    {
                        field.field_name: product.raw_value(field.field_name)
                        for field in product.raw_inputs
                    },
                )
                candidates.extend(extracted.candidates)
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

            # If no candidates from custom extractor, convert HTML spec fields into candidates
            if not candidates and html_data.specifications:
                for spec in html_data.specifications:
                    candidates.append(
                        EvidenceCandidate(
                            candidate_id="evidence-cand-" + str(uuid4()),
                            source_id=fetched.source.source_id,
                            url=fetched.source.canonical_url,
                            attribute=spec.attribute,
                            raw_value=spec.raw_value,
                            normalized_candidate=spec.normalized_value,
                            unit=spec.unit,
                            source_text=spec.source_text or f"{spec.attribute}: {spec.raw_value}",
                            evidence_type=spec.evidence_type,
                            status=spec.evidence_type,
                            location={k: str(v) for k, v in spec.location.items()},
                        )
                    )

            job.evidence_count = len(candidates)
            product = self._attach_candidates(product, candidates)

            # Build VerifiedProductSourceContext
            brand_val = (
                product.identity.brand.normalized_value
                if product.identity and product.identity.brand
                else str(product.raw_value("Unilog_Brand") or product.raw_value("E1_Brand") or "")
            )
            mpn_val = (
                product.identity.manufacturer_part_number.normalized_value
                if product.identity and product.identity.manufacturer_part_number
                else str(
                    product.raw_value("Mfg_Part_Num")
                    or product.raw_value("SKU - MY_PART_NUMBER")
                    or ""
                )
            )
            job.verified_source_context = VerifiedProductSourceContext(
                product_id=product.product_id,
                manufacturer=profile.canonical_name,
                brand=brand_val or None,
                mpn=mpn_val or None,
                canonical_product_url=fetched.source.canonical_url,
                source_id=fetched.source.source_id,
                source_authority="SECONDARY" if is_secondary else "AUTHORITATIVE",
                source_type="AUTHORIZED_DISTRIBUTOR" if is_secondary else "MANUFACTURER_PAGE",
                page_title=html_data.title,
                page_description=html_data.description,
                page_text=_build_clean_page_text(html_data),
                structured_facts=[
                    {"attribute": s.attribute, "raw_value": s.raw_value, "unit": s.unit}
                    for s in html_data.specifications
                ],
                image_urls=html_data.gallery_images
                or ([html_data.primary_image_url] if html_data.primary_image_url else []),
                document_urls=html_data.document_urls,
                evidence_references=list(evidence_references(product)),
            )

            # Discover assets
            try:
                discovered_assets = self.asset_discovery.discover_from_html(
                    product=product,
                    html_text=html_text,
                    base_url=fetched.source.canonical_url,
                    source_id=fetched.source.source_id,
                    verified_domains=(
                        profile.verified_domains or (fetched.source.manufacturer_domain,)
                    ),
                    manufacturer_key=profile.canonical_name,
                )
                product = self.asset_discovery.attach_to_product(product, discovered_assets)
                job.asset_discovery_status = "success"
                job.assets_discovered_count = len(product.digital_assets)
            except Exception as exc:
                job.asset_discovery_status = "failed"
                job.asset_discovery_error = f"{type(exc).__name__}: {exc}"
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
                    "verified_domains_available": discovery.verified_domains_available,
                    "domains_attempted": discovery.domains_attempted,
                    "selected_domain": discovery.selected_domain,
                    "domain_attempt_failure_reasons": discovery.domain_attempt_failure_reasons,
                }
            )
            return product, recovery_job
        best = found[0]
        is_secondary = best.source_kind == SourceKind.DISTRIBUTOR_PRODUCT_PAGE
        decision = (
            SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE
            if is_secondary
            else SourceDecision.CANDIDATE_MANUFACTURER_SOURCE
        )
        candidate_source = SourceRecord(
            canonical_url=best.url,
            original_url=best.url,
            source_kind=best.source_kind,
            decision=decision,
            manufacturer_id=profile.manufacturer_id,
            manufacturer_domain=_host_of(best.url),
            verified_domains=profile.verified_domains if not is_secondary else (),
            product_id=product.product_id,
        )
        if is_secondary:
            verified_source = self.verifier.verify_secondary_source(
                candidate_source, profile, _product_terms(product)
            )
            if verified_source.decision != SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE:
                recovery_job = failed_job.model_copy(
                    update={
                        "state": ManufacturerJobState.REVIEW_REQUIRED,
                        "error": verified_source.decision.value,
                        "failure_reason": Phase5FailureReason.DOMAIN_UNVERIFIED,
                        "verified_domains_available": discovery.verified_domains_available,
                        "domains_attempted": discovery.domains_attempted,
                        "selected_domain": discovery.selected_domain,
                        "domain_attempt_failure_reasons": discovery.domain_attempt_failure_reasons,
                    }
                )
                return product, recovery_job
        else:
            verified_source = self.verifier.verify_source(
                candidate_source, profile, _product_terms(product)
            )
            if verified_source.decision != SourceDecision.VERIFIED_MANUFACTURER_SOURCE:
                recovery_job = failed_job.model_copy(
                    update={
                        "state": ManufacturerJobState.REVIEW_REQUIRED,
                        "error": verified_source.decision.value,
                        "failure_reason": Phase5FailureReason.DOMAIN_UNVERIFIED,
                        "verified_domains_available": discovery.verified_domains_available,
                        "domains_attempted": discovery.domains_attempted,
                        "selected_domain": discovery.selected_domain,
                        "domain_attempt_failure_reasons": discovery.domain_attempt_failure_reasons,
                    }
                )
                return product, recovery_job
        res_prod, res_job = self.process(product, verified_source, profile)
        res_job.verified_domains_available = discovery.verified_domains_available
        res_job.domains_attempted = discovery.domains_attempted
        res_job.selected_domain = discovery.selected_domain or _host_of(best.url)
        res_job.domain_attempt_failure_reasons = discovery.domain_attempt_failure_reasons
        res_job.identity_score = best.identity_score
        match_type = (
            best.mpn_match_type.value
            if hasattr(best.mpn_match_type, "value")
            else str(best.mpn_match_type)
        )
        res_job.mpn_match_type = match_type
        res_job.raw_mpn_match = best.raw_mpn_match
        res_job.transformed_mpn_match = best.transformed_mpn_match
        res_job.identity_rejection_reason = best.rejection_reason
        return res_prod, res_job

    def _attach_candidates(
        self, product: ProductTruth, candidates: list[EvidenceCandidate]
    ) -> ProductTruth:
        for evidence_candidate in candidates:
            if evidence_candidate.status in {EvidenceStatus.UNRESOLVED, EvidenceStatus.INFERRED}:
                candidate_status = ValueStatus.INFERRED
            else:
                candidate_status = ValueStatus.CANDIDATE
            attribute_id = "attribute-" + "-".join(evidence_candidate.attribute.casefold().split())
            candidate_id = evidence_candidate.candidate_id or ("evidence-cand-" + str(uuid4()))
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
    is_secondary = (
        source.decision == SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE
        or source.source_kind == SourceKind.DISTRIBUTOR_PRODUCT_PAGE
    )
    result.sources.append(
        Source(
            source_id=source.source_id,
            source_type=SourceType.AUTHORIZED_DISTRIBUTOR
            if is_secondary
            else SourceType.MANUFACTURER_PAGE
            if source.source_kind == SourceKind.MANUFACTURER_PRODUCT_PAGE
            else SourceType.MANUFACTURER_DOCUMENT,
            authority=SourceAuthority.SECONDARY if is_secondary else SourceAuthority.AUTHORITATIVE,
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


def _build_clean_page_text(data: ExtractedProductData) -> str:
    sections: list[str] = []
    if data.title:
        sections.append(f"PRODUCT TITLE: {data.title}")
    if data.description:
        sections.append(f"PRODUCT DESCRIPTION: {data.description}")
    if data.features:
        features_text = "\n".join(f"- {f}" for f in data.features[:20])
        sections.append(f"FEATURES:\n{features_text}")
    if data.specifications:
        specs_text = "\n".join(f"- {s.attribute}: {s.raw_value}" for s in data.specifications[:50])
        sections.append(f"SPECIFICATIONS:\n{specs_text}")
    if data.document_urls:
        docs_text = "\n".join(f"- {u}" for u in data.document_urls[:10])
        sections.append(f"DOCUMENT LINKS:\n{docs_text}")
    return "\n\n".join(sections)


