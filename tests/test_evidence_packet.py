"""Unit tests for ProductEvidencePacket domain value object."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from unilog_product_intelligence.domain.conflicts import ConflictResolution, EvidenceConflict
from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.domain.source_context import VerifiedProductSourceContext
from unilog_product_intelligence.domain.truth import SourceAuthority
from unilog_product_intelligence.enrichment.models import EvidenceReference


def test_evidence_packet_construction() -> None:
    source_ctx = VerifiedProductSourceContext(
        product_id="p-100",
        canonical_product_url="https://www.milwaukeetool.com/Products/2804-20",
        source_id="src-1",
        source_authority="AUTHORITATIVE",
        source_type="MANUFACTURER_PAGE",
    )
    ev = EvidenceReference(
        evidence_id="ev-1",
        source_id="src-1",
        source_url="https://www.milwaukeetool.com/Products/2804-20",
        evidence_text="1200 in-lbs of torque",
    )
    packet = ProductEvidencePacket(
        product_id="p-100",
        mpn="2804-20",
        manufacturer="Milwaukee",
        brand="Milwaukee",
        canonical_product_url="https://www.milwaukeetool.com/Products/2804-20",
        source_context=source_ctx,
        evidence=(ev,),
        structured_facts=({"attribute": "voltage", "raw_value": "18V", "unit": "V"},),
        features=("Peak torque of 1200 in-lbs", "Compact design"),
        document_urls=("https://www.milwaukeetool.com/manuals/2804-20.pdf",),
        image_urls=("https://www.milwaukeetool.com/images/2804-20.jpg",),
        source_authority=SourceAuthority.AUTHORITATIVE,
        identity_score=0.95,
    )

    assert packet.product_id == "p-100"
    assert packet.mpn == "2804-20"
    assert packet.manufacturer == "Milwaukee"
    assert packet.canonical_product_url == "https://www.milwaukeetool.com/Products/2804-20"
    assert len(packet.evidence) == 1
    assert packet.evidence[0].evidence_text == "1200 in-lbs of torque"
    assert len(packet.structured_facts) == 1
    assert len(packet.features) == 2
    assert len(packet.document_urls) == 1
    assert packet.source_authority == SourceAuthority.AUTHORITATIVE
    assert packet.identity_score == 0.95


def test_evidence_packet_is_immutable() -> None:
    packet = ProductEvidencePacket(
        product_id="p-200",
        mpn="DW735X",
        manufacturer="DEWALT",
    )
    with pytest.raises(ValidationError):
        # frozen=True forbids attribute assignment
        packet.product_id = "p-201"  # type: ignore[misc]


def test_evidence_packet_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        ProductEvidencePacket(
            product_id="p-300",
            unknown_arbitrary_field="not_allowed",  # type: ignore[call-arg]
        )


def test_evidence_packet_with_conflicts() -> None:
    conflict = EvidenceConflict(
        attribute="voltage",
        values=("120V", "125V"),
        evidence_ids=("ev-1", "ev-2"),
        source_authorities=(SourceAuthority.AUTHORITATIVE, SourceAuthority.AUTHORITATIVE),
        resolution=ConflictResolution.ESCALATE_TO_STRONG_MODEL,
    )
    packet = ProductEvidencePacket(
        product_id="p-400",
        mpn="M18",
        conflicts=(conflict,),
    )
    assert len(packet.conflicts) == 1
    assert packet.conflicts[0].attribute == "voltage"
    assert packet.conflicts[0].resolution == ConflictResolution.ESCALATE_TO_STRONG_MODEL
