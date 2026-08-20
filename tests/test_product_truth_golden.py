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
    assert result.publication_safe is True
    assert result.total_attributes == len(case.expected_attributes)
    assert result.grounded_attributes == len(case.expected_attributes)
    assert result.unresolved_attributes == 0
    assert len(result.violations) == 0


@pytest.mark.parametrize(
    "fixture_name",
    ["dewalt_dw735x", "milwaukee_2804_20", "3m_dcb518asts06g"],
)
def test_real_html_fixture_extraction_and_truth_audit(fixture_name: str) -> None:
    """Test full extraction and truth auditing from real HTML fixtures."""
    import json
    from pathlib import Path

    from unilog_product_intelligence.enrichment.evidence_validator import (
        EvidenceConstraintValidator,
    )
    from unilog_product_intelligence.enrichment.schemas import AttributeProposal
    from unilog_product_intelligence.retrieval.html_extractor import (
        HtmlProductEvidenceExtractor,
    )

    fixture_dir = Path(__file__).parent / "golden" / "fixtures" / fixture_name
    html_path = fixture_dir / "source.html"
    json_path = fixture_dir / "expected.json"

    assert html_path.exists()
    assert json_path.exists()

    html_content = html_path.read_text(encoding="utf-8")
    expected_data = json.loads(json_path.read_text(encoding="utf-8"))

    # Extract specs from HTML
    extractor = HtmlProductEvidenceExtractor()
    extracted = extractor.extract(html_content, expected_data["canonical_url"])

    # Build evidence references from extracted specs
    evidence_refs: list[EvidenceReference] = []
    specs: list[StructuredSpec] = []
    proposals: list[AttributeProposal] = []
    final_attrs: list[FinalAttribute] = []

    for i, spec in enumerate(extracted.specifications):
        ev_id = f"ev-{fixture_name}-{i}"
        ev = EvidenceReference(
            evidence_id=ev_id,
            source_id="src-html",
            source_url=expected_data["canonical_url"],
            evidence_text=f"{spec.attribute}: {spec.raw_value}",
            source_authority=SourceAuthority.AUTHORITATIVE,
        )
        evidence_refs.append(ev)
        specs.append(
            StructuredSpec(
                attribute=spec.attribute,
                raw_value=spec.raw_value,
                evidence_id=ev_id,
            )
        )
        proposals.append(
            AttributeProposal(
                attribute=spec.attribute,
                value=spec.raw_value,
                evidence_ids=(ev_id,),
            )
        )
        final_attrs.append(
            FinalAttribute(
                attribute=spec.attribute,
                value=spec.raw_value,
                provenance_kind=ProvenanceKind.EXTRACTED_HTML,
                evidence_id=ev_id,
                source_url=expected_data["canonical_url"],
                source_authority=SourceAuthority.AUTHORITATIVE,
            )
        )

    packet = ProductEvidencePacket(
        product_id=expected_data["product_id"],
        mpn=expected_data["mpn"],
        manufacturer=expected_data["manufacturer"],
        canonical_product_url=expected_data["canonical_url"],
        evidence=tuple(evidence_refs),
        structured_facts=tuple(specs),
        source_authority=SourceAuthority.AUTHORITATIVE,
    )

    # 1. EvidenceConstraintValidator must accept all valid extracted proposals
    validator = EvidenceConstraintValidator()
    val_result = validator.validate(proposals, packet)
    assert len(val_result.rejected) == 0
    assert len(val_result.accepted) == len(proposals)

    # 2. TruthAudit must confirm publication safety
    auditor = TruthAudit()
    audit_result = auditor.audit(packet=packet, final_attributes=final_attrs)
    assert audit_result.audit_passed is True
    assert audit_result.publication_safe is True
    assert audit_result.grounded_attributes == len(final_attrs)
    assert len(audit_result.violations) == 0
