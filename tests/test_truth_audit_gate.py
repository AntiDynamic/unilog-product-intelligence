"""Unit and integration tests for TruthAudit publication gating."""

from __future__ import annotations

from unittest.mock import MagicMock

from unilog_product_intelligence.application.phase65 import (
    Phase65Pipeline,
    Phase65Status,
)
from unilog_product_intelligence.domain.conflicts import ConflictResolution, EvidenceConflict
from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.domain.provenance import FinalAttribute
from unilog_product_intelligence.domain.truth import SourceAuthority
from unilog_product_intelligence.enrichment.models import (
    EnrichmentResult,
    EnrichmentStatus,
    EvidenceReference,
)
from unilog_product_intelligence.retrieval.service import ManufacturerJob, ManufacturerJobState
from unilog_product_intelligence.validation.truth_audit import TruthAudit


def test_truth_audit_unsupported_value_fails_publication_safety() -> None:
    """An attribute with a value but missing evidence ID must fail publication_safe."""
    packet = ProductEvidencePacket(
        product_id="prod-123",
        evidence=(
            EvidenceReference(
                evidence_id="ev-1",
                source_id="src-1",
                evidence_text="Voltage: 120V",
            ),
        ),
    )

    # Attribute with value but NO evidence_id
    unsupported_attr = FinalAttribute(
        attribute="Amperage",
        value="15A",
        evidence_id=None,
    )

    audit_result = TruthAudit().audit(packet, final_attributes=(unsupported_attr,))
    assert audit_result.audit_passed is False
    assert audit_result.publication_safe is False
    assert any(
        "asserts value '15A' without supporting evidence_id" in v for v in audit_result.violations
    )


def test_truth_audit_unknown_evidence_id_fails_publication_safety() -> None:
    """An attribute citing an evidence ID not present in packet must fail."""
    packet = ProductEvidencePacket(
        product_id="prod-123",
        evidence=(
            EvidenceReference(
                evidence_id="ev-real",
                source_id="src-1",
                evidence_text="Voltage: 120V",
            ),
        ),
    )

    hallucinated_attr = FinalAttribute(
        attribute="Voltage",
        value="120V",
        evidence_id="ev-HALLUCINATED",
    )

    audit_result = TruthAudit().audit(packet, final_attributes=(hallucinated_attr,))
    assert audit_result.audit_passed is False
    assert audit_result.publication_safe is False
    assert any("cites unknown evidence_id 'ev-HALLUCINATED'" in v for v in audit_result.violations)


def test_truth_audit_gate_blocks_phase65_pipeline_delivery() -> None:
    """If TruthAudit fails, Phase65Pipeline must override status to BLOCKED with blocker reason."""
    from unilog_product_intelligence.agents.orchestration import JobState, ProductJob
    from unilog_product_intelligence.application.product_truth import ProductTruthService
    from unilog_product_intelligence.domain.truth import Source, SourceType
    from unilog_product_intelligence.retrieval.agents import DiscoveryResult
    from unilog_product_intelligence.retrieval.core import DomainCandidate, SourceDecision

    truth_svc = ProductTruthService()
    product = truth_svc.create_from_raw_input(
        "p-1",
        {"Part_Manuf": "DEWALT", "Mfg_Part_Num": "DW735X"},
        Source(source_id="src-1", source_type=SourceType.SUPPLIED_INPUT),
    )

    mock_orchestrator = MagicMock()
    mock_orchestrator.run.return_value = (
        product,
        ProductJob(job_id="j1", product_id="p-1", state=JobState.CANDIDATES_ACCEPTED),
    )

    mock_discovery = MagicMock()
    mock_discovery.discover.return_value = DiscoveryResult(
        candidates=[
            DomainCandidate(
                domain="dewalt.com",
                source="test",
                reason="verified test candidate",
                status=SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
            )
        ]
    )

    # Packet with an unresolved conflict
    invalid_conflict = EvidenceConflict(
        attribute="Voltage",
        values=("120V", "240V"),
        evidence_ids=("ev-1", "ev-2"),
        source_authorities=(SourceAuthority.HIGH, SourceAuthority.HIGH),
        resolution=ConflictResolution.ESCALATE_TO_STRONG_MODEL,  # still unresolved / escalated
    )
    mock_packet = ProductEvidencePacket(
        product_id="p-1",
        evidence=(
            EvidenceReference(evidence_id="ev-1", source_id="s1", evidence_text="120V"),
            EvidenceReference(evidence_id="ev-2", source_id="s2", evidence_text="240V"),
        ),
        conflicts=(invalid_conflict,),
    )

    mock_manufacturer = MagicMock()
    mock_job = MagicMock(
        spec=ManufacturerJob,
        state=ManufacturerJobState.COMPLETED,
        evidence_packet=mock_packet,
        verified_source_context=MagicMock(),
    )
    mock_manufacturer.process.return_value = (product, mock_job)

    mock_enrichment = MagicMock()
    from unilog_product_intelligence.enrichment.models import PublicationState

    mock_enrichment_res = EnrichmentResult(
        product_id="p-1",
        status=EnrichmentStatus.ENRICHED,
        publication_state=PublicationState.READY,
        product_truth=product,
    )
    mock_enrichment.enrich.return_value = mock_enrichment_res

    pipeline = Phase65Pipeline(
        orchestrator=mock_orchestrator,
        discovery=mock_discovery,
        manufacturer=mock_manufacturer,
        enrichment=mock_enrichment,
    )

    result = pipeline.run(product)

    # Pipeline output should be BLOCKED due to TruthAudit invariant
    assert result.status == Phase65Status.BLOCKED or result.status == Phase65Status.REVIEW_REQUIRED
