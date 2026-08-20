"""Pipeline invariant tests: immutability, evidence grounding, and anti-hallucination."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.domain.models import FeatureEvidence, StructuredSpec
from unilog_product_intelligence.domain.provenance import FinalAttribute, ProvenanceKind
from unilog_product_intelligence.enrichment.models import EvidenceReference
from unilog_product_intelligence.validation.truth_audit import TruthAudit


def test_evidence_grounding_invariant_catches_hallucinations() -> None:
    """TruthAudit must catch any attribute value citing an ungrounded or invented evidence_id."""
    ev1 = EvidenceReference(evidence_id="ev-real-1", source_id="src-1", evidence_text="120V")
    packet = ProductEvidencePacket(
        product_id="p-inv-1",
        evidence=(ev1,),
    )

    # 1 valid attribute, 1 hallucinated attribute
    attrs = [
        FinalAttribute(
            attribute="voltage",
            value="120V",
            provenance_kind=ProvenanceKind.EXTRACTED_HTML,
            evidence_id="ev-real-1",
        ),
        FinalAttribute(
            attribute="battery_capacity",
            value="5.0 Ah",
            provenance_kind=ProvenanceKind.MODEL_INFERRED,
            evidence_id="ev-INVENTED-99",  # not in packet
        ),
    ]

    audit = TruthAudit().audit(packet, final_attributes=attrs)
    assert audit.audit_passed is False
    assert len(audit.violations) == 1
    assert "battery_capacity" in audit.violations[0]
    assert "ev-INVENTED-99" in audit.violations[0]
    assert audit.grounded_attributes == 1
    assert audit.total_attributes == 2


def test_packet_end_to_end_immutability_invariant() -> None:
    """ProductEvidencePacket and its child models cannot be mutated by any downstream consumer."""
    spec = StructuredSpec(attribute="torque", raw_value="1200 in-lbs", unit="in-lbs")
    feat = FeatureEvidence(name="Compact brushless motor")
    ev = EvidenceReference(evidence_id="ev-1", source_id="src-1", evidence_text="1200 in-lbs")

    packet = ProductEvidencePacket(
        product_id="p-inv-2",
        mpn="2804-20",
        evidence=(ev,),
        structured_facts=(spec,),
        features=(feat,),
        document_urls=("https://example.com/manual.pdf",),
    )

    # Top-level field mutation rejected
    with pytest.raises(ValidationError):
        packet.product_id = "modified-id"  # type: ignore[misc]

    # Child model field mutation rejected
    with pytest.raises(ValidationError):
        packet.structured_facts[0].raw_value = "999"  # type: ignore[misc]

    with pytest.raises(ValidationError):
        packet.features[0].name = "Mutated feature"  # type: ignore[misc]

    # Tuple collections are immutable (no append/pop)
    assert isinstance(packet.structured_facts, tuple)
    assert isinstance(packet.features, tuple)
    assert isinstance(packet.document_urls, tuple)
