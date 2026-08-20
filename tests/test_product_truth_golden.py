"""Golden truth regression test suite."""

from __future__ import annotations

import pytest

from tests.golden.golden_cases import GOLDEN_CASES, GoldenProductCase
from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.domain.models import StructuredSpec
from unilog_product_intelligence.domain.provenance import FinalAttribute, ProvenanceKind
from unilog_product_intelligence.domain.truth import SourceAuthority
from unilog_product_intelligence.enrichment.models import EvidenceReference
from unilog_product_intelligence.validation.truth_audit import TruthAudit


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.product_id)
def test_golden_product_truth_audit(case: GoldenProductCase) -> None:
    """Verify that golden product cases produce fully grounded, valid TruthAudit results."""
    # Build synthetic packet matching golden case expectations
    evidence_refs = tuple(
        EvidenceReference(
            evidence_id=f"ev-{case.product_id}-{i}",
            source_id="src-1",
            source_url=f"https://www.{case.expected_canonical_domain}/product/{case.mpn}",
            evidence_text=f"{attr}: {val}",
            source_authority=SourceAuthority.AUTHORITATIVE,
        )
        for i, (attr, val) in enumerate(case.expected_attributes.items())
    )

    specs = tuple(
        StructuredSpec(attribute=attr, raw_value=str(val), evidence_id=evidence_refs[i].evidence_id)
        for i, (attr, val) in enumerate(case.expected_attributes.items())
    )

    packet = ProductEvidencePacket(
        product_id=case.product_id,
        mpn=case.mpn,
        manufacturer=case.manufacturer,
        brand=case.brand,
        canonical_product_url=f"https://www.{case.expected_canonical_domain}/product/{case.mpn}",
        evidence=evidence_refs,
        structured_facts=specs,
        source_authority=SourceAuthority.AUTHORITATIVE,
    )

    # Convert to FinalAttributes
    final_attrs = [
        FinalAttribute(
            attribute=attr,
            value=val,
            provenance_kind=ProvenanceKind.EXTRACTED_HTML,
            evidence_id=evidence_refs[i].evidence_id,
            source_url=packet.canonical_product_url,
            source_authority=SourceAuthority.AUTHORITATIVE,
        )
        for i, (attr, val) in enumerate(case.expected_attributes.items())
    ]

    auditor = TruthAudit()
    result = auditor.audit(packet=packet, final_attributes=final_attrs)

    assert result.audit_passed is True
    assert result.total_attributes == len(case.expected_attributes)
    assert result.grounded_attributes == len(case.expected_attributes)
    assert result.unresolved_attributes == 0
    assert len(result.violations) == 0
