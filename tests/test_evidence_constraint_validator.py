"""Unit tests for EvidenceConstraintValidator."""

from __future__ import annotations

from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.enrichment.evidence_validator import (
    EvidenceConstraintValidator,
)
from unilog_product_intelligence.enrichment.models import EvidenceReference
from unilog_product_intelligence.enrichment.schemas import AttributeProposal


def _make_packet(*evidence_ids: str) -> ProductEvidencePacket:
    """Build a minimal packet with the given evidence IDs."""
    refs = tuple(
        EvidenceReference(
            evidence_id=eid,
            source_id="src-1",
            evidence_text=f"Specs: 120V voltage, 15A amps, 1800W wattage for {eid}",
        )
        for eid in evidence_ids
    )
    return ProductEvidencePacket(product_id="p-test", evidence=refs)


_VALIDATOR = EvidenceConstraintValidator()


def test_proposal_with_valid_evidence_id_accepted() -> None:
    packet = _make_packet("ev-1", "ev-2")
    proposals = [
        AttributeProposal(attribute="voltage", value="120V", evidence_ids=("ev-1",)),
    ]
    result = _VALIDATOR.validate(proposals, packet)
    assert len(result.accepted) == 1
    assert len(result.rejected) == 0
    assert result.accepted[0].attribute == "voltage"


def test_proposal_with_missing_evidence_ids_rejected() -> None:
    packet = _make_packet("ev-1")
    proposals = [
        AttributeProposal(attribute="voltage", value="120V"),  # empty evidence_ids
    ]
    result = _VALIDATOR.validate(proposals, packet)
    assert len(result.rejected) == 1
    assert len(result.accepted) == 0
    assert "missing evidence IDs" in result.rejection_reasons[0]


def test_proposal_with_unknown_evidence_id_rejected() -> None:
    packet = _make_packet("ev-1")
    proposals = [
        AttributeProposal(attribute="voltage", value="240V", evidence_ids=("ev-99",)),
    ]
    result = _VALIDATOR.validate(proposals, packet)
    assert len(result.rejected) == 1
    assert "unknown evidence IDs" in result.rejection_reasons[0]
    assert "ev-99" in result.rejection_reasons[0]


def test_proposal_with_partial_unknown_ids_rejected() -> None:
    """Even one unknown ID in the tuple causes rejection."""
    packet = _make_packet("ev-1", "ev-2")
    proposals = [
        AttributeProposal(attribute="amps", value="15A", evidence_ids=("ev-1", "ev-FAKE")),
    ]
    result = _VALIDATOR.validate(proposals, packet)
    assert len(result.rejected) == 1
    assert "ev-FAKE" in result.rejection_reasons[0]


def test_empty_packet_rejects_all_proposals() -> None:
    """No evidence in packet means all proposals citing any ID are rejected."""
    packet = ProductEvidencePacket(product_id="p-empty")
    proposals = [
        AttributeProposal(attribute="voltage", value="120V", evidence_ids=("ev-1",)),
        AttributeProposal(attribute="amps", value="15A"),
    ]
    result = _VALIDATOR.validate(proposals, packet)
    assert len(result.rejected) == 2
    assert len(result.accepted) == 0


def test_mixed_valid_and_invalid_proposals() -> None:
    """Accepted and rejected proposals are correctly separated."""
    packet = _make_packet("ev-good")
    proposals = [
        AttributeProposal(attribute="voltage", value="120V", evidence_ids=("ev-good",)),
        AttributeProposal(attribute="amps", value="15A", evidence_ids=("ev-bad",)),
        AttributeProposal(attribute="wattage", value="1800W"),  # no IDs
    ]
    result = _VALIDATOR.validate(proposals, packet)
    assert len(result.accepted) == 1
    assert len(result.rejected) == 2
    assert result.accepted[0].attribute == "voltage"
