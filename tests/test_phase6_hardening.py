"""Regression coverage for Phase 6 hardening invariants."""

import pytest

from test_phase6_enrichment import FakeProvider, _product
from unilog_product_intelligence.domain.truth import SourceType
from unilog_product_intelligence.enrichment import (
    AttributePlanner,
    EnrichmentService,
    EvidenceGroundedEnrichmentAgent,
    PostgresEnrichmentRepository,
    ReferencePack,
    ValidationPipeline,
)
from unilog_product_intelligence.enrichment.agent import evidence_references
from unilog_product_intelligence.enrichment.models import (
    EnrichmentCandidate,
    EnrichmentResult,
    EvidenceReference,
    FinalAttributeStatus,
    PublicationState,
    ReferenceAvailability,
    ValidationResult,
    ValidationSeverity,
)


class RecordingCursor:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, object]] = []
        self.fail = fail
        self.closed = False

    def execute(self, statement: str, parameters: object = ()) -> None:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append((statement, parameters))

    def close(self) -> None:
        self.closed = True


class RecordingConnection:
    def __init__(self, fail: bool = False) -> None:
        self.cursor_instance = RecordingCursor(fail=fail)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> RecordingCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_cache_key_changes_when_source_content_changes() -> None:
    product = _product()
    plans = AttributePlanner(
        reference_pack=ReferencePack(ReferenceAvailability.REFERENCE_UNAVAILABLE, {})
    ).plan(product)
    first = EvidenceReference(
        evidence_id="ev-1",
        source_id="manufacturer-source",
        evidence_text="Material: stainless steel",
        source_content_hash="content-a",
    )
    second = first.model_copy(update={"source_content_hash": "content-b"})
    key_a = EvidenceGroundedEnrichmentAgent.cache_key(
        product, plans, [first], "model-a", "schema-a"
    )
    key_b = EvidenceGroundedEnrichmentAgent.cache_key(
        product, plans, [second], "model-a", "schema-a"
    )
    assert key_a != key_b


def test_inferred_candidate_remains_review_required() -> None:
    product = _product()
    plans = AttributePlanner().plan(product)
    candidate = EnrichmentCandidate(
        candidate_id="inferred-1",
        product_id=product.product_id,
        attribute_id="material",
        attribute="Material",
        value="Stainless Steel",
        raw_value="stainless steel",
        normalized_value="Stainless Steel",
        source_id="manufacturer-source",
        evidence_ids=("ev-1",),
        evidence_text="Material: stainless steel",
        evidence=(
            EvidenceReference(
                evidence_id="ev-1",
                source_id="manufacturer-source",
                evidence_text="Material: stainless steel",
            ),
        ),
        status=FinalAttributeStatus.INFERRED,
        candidate_reason="Calculated from supplied evidence.",
    )
    validated, validations, reviews = ValidationPipeline().validate(product, plans, [candidate])
    assert validated[0].status == FinalAttributeStatus.INFERRED
    assert any(item.validator == "evidence_directness" for item in validations)
    publication = ValidationPipeline().publication_state(plans, validated, validations, reviews)
    assert publication != PublicationState.READY


def test_repeated_service_run_does_not_duplicate_candidates_or_evidence() -> None:
    product = _product()
    service = EnrichmentService(
        planner=AttributePlanner(), agent=EvidenceGroundedEnrichmentAgent(FakeProvider())
    )
    first = service.enrich(product)
    second = service.enrich(first.product_truth)
    material = second.product_truth.attribute("material")
    assert len(material.candidates) == 1
    assert len(second.product_truth.evidence) == 1
    assert len(second.product_truth.conflicts) == len(first.product_truth.conflicts)


def test_postgres_repository_commits_and_uses_stable_validation_id() -> None:
    validation = ValidationResult(
        validator="schema",
        passed=True,
        severity=ValidationSeverity.INFO,
        message="ok",
        attribute="material",
    )
    result = EnrichmentResult(
        product_id="product-1",
        status="REVIEW_REQUIRED",
        publication_state=PublicationState.REVIEW_REQUIRED,
        validations=(validation,),
    )
    connection = RecordingConnection()
    repository = PostgresEnrichmentRepository(connection)
    repository.save(result)
    repository.save(result)
    validation_calls = [
        parameters
        for statement, parameters in connection.cursor_instance.calls
        if "enrichment_validation_results" in statement
    ]
    assert len(validation_calls) == 2
    assert validation_calls[0][0] == validation_calls[1][0]
    assert connection.commits == 2
    assert connection.cursor_instance.closed


def test_postgres_repository_rolls_back_and_closes_on_failure() -> None:
    connection = RecordingConnection(fail=True)
    result = EnrichmentResult(
        product_id="product-1",
        status="REVIEW_REQUIRED",
        publication_state=PublicationState.REVIEW_REQUIRED,
        validations=(
            ValidationResult(
                validator="schema",
                passed=True,
                severity=ValidationSeverity.INFO,
                message="ok",
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="database unavailable"):
        PostgresEnrichmentRepository(connection).save(result)
    assert connection.rollbacks == 1
    assert connection.cursor_instance.closed


def test_supplied_input_evidence_is_not_exposed_to_enrichment() -> None:
    product = _product()
    product.sources[0].source_type = SourceType.SUPPLIED_INPUT
    assert evidence_references(product) == ()
