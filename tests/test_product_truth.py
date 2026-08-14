import pytest

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.lifecycle import (
    InvalidLifecycleTransition,
    assert_transition,
)
from unilog_product_intelligence.domain.truth import (
    CandidateValue,
    Conflict,
    ConflictState,
    ConflictType,
    Evidence,
    EvidenceType,
    LifecycleState,
    Source,
    SourceAuthority,
    SourceType,
    ValidationState,
    ValueStatus,
)


def _source() -> Source:
    return Source(
        source_id="source-structural-test",
        source_type=SourceType.SUPPLIED_INPUT,
        authority=SourceAuthority.HIGH,
    )


def _classified_product():
    service = ProductTruthService()
    return service.add_classification(
        service.create_from_raw_input(
            "product-structural-test",
            {
                "Mfg_Part_Num": "raw-part",
                "Part_Manuf": "raw-manufacturer",
                "Unilog_Brand": "-- No Unilog Brand --",
            },
            _source(),
        ),
        classification={"department": "structural-test"},
    )


def test_raw_input_and_placeholder_are_preserved() -> None:
    product = ProductTruthService().create_from_raw_input(
        "product-structural-test",
        {"Unilog_Brand": "-- No Unilog Brand --", "Mfg_Part_Num": "raw-part"},
        _source(),
    )

    assert product.raw_value("Unilog_Brand") == "-- No Unilog Brand --"
    assert product.identity.brand is not None
    assert product.identity.brand.normalized_value is None
    assert product.identity.brand.status == ValueStatus.MISSING


def test_candidate_lifecycle_requires_evidence_before_acceptance() -> None:
    service = ProductTruthService()
    product = _classified_product()
    candidate = CandidateValue(
        candidate_id="candidate-1",
        raw_value="raw-value",
        normalized_value="canonical-value",
        source_ids=["source-structural-test"],
    )
    product = service.add_attribute_candidate(
        product, "attribute-1", candidate, "Canonical Attribute"
    )
    assert product.lifecycle_state == LifecycleState.ENRICHED

    with pytest.raises(ValueError, match="without evidence"):
        service.validate_candidate(
            product,
            "attribute-1",
            "candidate-1",
            accepted=True,
            reason="not yet supported",
        )

    evidence = Evidence(
        evidence_id="evidence-1",
        source_id="source-structural-test",
        product_id=product.product_id,
        attribute_id="attribute-1",
        candidate_id="candidate-1",
        quoted_text="concise structural evidence",
        evidence_type=EvidenceType.DIRECT_TEXT,
    )
    product = service.attach_evidence(product, evidence)
    product = service.validate_candidate(
        product,
        "attribute-1",
        "candidate-1",
        accepted=True,
        reason="evidence attached",
    )
    assert product.attribute("attribute-1").candidates[0].status == ValueStatus.VERIFIED
    assert product.attribute("attribute-1").validation_state == ValidationState.PASSED


def test_candidates_coexist_and_conflict_resolution_is_explicit() -> None:
    service = ProductTruthService()
    product = _classified_product()
    for candidate_id in ("candidate-a", "candidate-b"):
        product = service.add_attribute_candidate(
            product,
            "attribute-1",
            CandidateValue(candidate_id=candidate_id, normalized_value=candidate_id),
            "Canonical Attribute",
        )
    conflict = Conflict(
        conflict_id="conflict-1",
        product_id=product.product_id,
        attribute_id="attribute-1",
        candidate_ids=["candidate-a", "candidate-b"],
        conflict_type=ConflictType.VALUE_DISAGREEMENT,
    )
    product = service.create_conflict(product, conflict)
    assert product.lifecycle_state == LifecycleState.CONFLICTED
    assert len(product.attribute("attribute-1").candidates) == 2

    product = service.resolve_conflict(
        product, "conflict-1", "candidate-a", "source review", "reviewer"
    )
    assert product.conflicts[0].state == ConflictState.RESOLVED
    assert product.conflicts[0].resolved_by == "reviewer"


def test_invalid_lifecycle_transition_is_rejected() -> None:
    with pytest.raises(InvalidLifecycleTransition):
        assert_transition(LifecycleState.RAW, LifecycleState.READY)
