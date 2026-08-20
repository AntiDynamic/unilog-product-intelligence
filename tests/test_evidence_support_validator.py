"""Unit tests for EvidenceSupportValidator and semantic grounding enforcement."""

from __future__ import annotations

from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.enrichment.evidence_support import (
    EvidenceSupportValidator,
)
from unilog_product_intelligence.enrichment.evidence_validator import (
    EvidenceConstraintValidator,
)
from unilog_product_intelligence.enrichment.models import EvidenceReference
from unilog_product_intelligence.enrichment.schemas import AttributeProposal


def test_numeric_value_matching_exact() -> None:
    validator = EvidenceSupportValidator()
    ev = EvidenceReference(
        evidence_id="ev-volt",
        source_id="src-1",
        evidence_text="Power Source: 18 V Lithium-Ion Battery Pack",
    )

    # 18V is supported
    res = validator.supports("Voltage", "18V", ev)
    assert res.supported is True

    # 18 V with UOM is supported
    res_uom = validator.supports("Voltage", "18", ev, uom="V")
    assert res_uom.supported is True


def test_numeric_value_mismatch_rejected() -> None:
    validator = EvidenceSupportValidator()
    ev = EvidenceReference(
        evidence_id="ev-volt",
        source_id="src-1",
        evidence_text="Power Source: 18 V Lithium-Ion Battery Pack",
    )

    # 24V is NOT in the evidence -> must be rejected
    res = validator.supports("Voltage", "24V", ev)
    assert res.supported is False
    assert "Numeric value mismatch" in (res.reason or "") or "does not contain" in (
        res.reason or ""
    )


def test_range_matching_supported() -> None:
    validator = EvidenceSupportValidator()
    ev = EvidenceReference(
        evidence_id="ev-rpm",
        source_id="src-1",
        evidence_text="No Load Speed: 0-550 / 0-2,000 RPM",
    )

    res = validator.supports("RPM", "0-550 / 0-2000 RPM", ev)
    assert res.supported is True


def test_categorical_token_matching() -> None:
    validator = EvidenceSupportValidator()
    ev = EvidenceReference(
        evidence_id="ev-color",
        source_id="src-1",
        evidence_text="Backing Material: Amber Polyimide Film with Silicone Adhesive",
    )

    # Amber is supported
    res_amber = validator.supports("Color", "Amber", ev)
    assert res_amber.supported is True

    # Polyimide is supported
    res_poly = validator.supports("Material", "Polyimide", ev)
    assert res_poly.supported is True

    # Blue is NOT supported
    res_blue = validator.supports("Color", "Blue", ev)
    assert res_blue.supported is False


def test_contradiction_detection_rejected() -> None:
    validator = EvidenceSupportValidator()
    ev = EvidenceReference(
        evidence_id="ev-drill",
        source_id="src-1",
        evidence_text="M18 FUEL 1/2 in. Cordless Hammer Drill/Driver",
    )

    # Corded explicitly contradicts Cordless
    res = validator.supports("Tool Type", "Corded Drill", ev)
    assert res.supported is False
    assert "Contradiction detected" in (res.reason or "")


def test_constraint_validator_rejects_wrong_value_with_real_evidence_id() -> None:
    """CRITICAL INVARIANT TEST: AI cites real evidence ID but hallucinates wrong value."""
    ev = EvidenceReference(
        evidence_id="ev-123",
        source_id="src-1",
        evidence_text="Motor Type: 18V Brushless Motor delivering 1200 in-lbs torque",
    )
    packet = ProductEvidencePacket(
        product_id="prod-1",
        evidence=(ev,),
    )
    validator = EvidenceConstraintValidator()

    # 1. Correct proposal -> ACCEPTED
    prop_valid = AttributeProposal(
        attribute="Voltage",
        value="18V",
        evidence_ids=("ev-123",),
    )
    res_valid = validator.validate((prop_valid,), packet)
    assert prop_valid in res_valid.accepted
    assert len(res_valid.rejected) == 0

    # 2. Wrong value citing real evidence ID -> REJECTED!
    prop_wrong = AttributeProposal(
        attribute="Voltage",
        value="24V",
        evidence_ids=("ev-123",),
    )
    res_wrong = validator.validate((prop_wrong,), packet)
    assert prop_wrong in res_wrong.rejected
    assert len(res_wrong.accepted) == 0
    assert any("evidence does not support value '24V'" in r for r in res_wrong.rejection_reasons)

    # 3. Hallucinated evidence ID -> REJECTED!
    prop_fake_id = AttributeProposal(
        attribute="Voltage",
        value="18V",
        evidence_ids=("ev-NONEXISTENT",),
    )
    res_fake = validator.validate((prop_fake_id,), packet)
    assert prop_fake_id in res_fake.rejected
    assert len(res_fake.accepted) == 0
    assert any("unknown evidence IDs" in r for r in res_fake.rejection_reasons)
