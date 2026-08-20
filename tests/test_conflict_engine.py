"""Unit tests for ConflictEngine and authority hierarchy resolution."""

from __future__ import annotations

from unilog_product_intelligence.domain.conflicts import ConflictResolution
from unilog_product_intelligence.domain.truth import SourceAuthority
from unilog_product_intelligence.enrichment.conflicts import ConflictEngine
from unilog_product_intelligence.enrichment.models import EnrichmentCandidate, EvidenceReference


def test_conflict_engine_no_conflict_when_values_agree() -> None:
    engine = ConflictEngine()
    ev1 = EvidenceReference(
        evidence_id="ev-1",
        source_id="src-1",
        source_authority="AUTHORITATIVE",
        evidence_text="Voltage: 120V",
    )
    ev2 = EvidenceReference(
        evidence_id="ev-2",
        source_id="src-2",
        source_authority="SECONDARY",
        evidence_text="Power supply: 120V",
    )
    c1 = EnrichmentCandidate(
        candidate_id="c-1",
        product_id="p-1",
        attribute_id="voltage",
        attribute="voltage",
        value="120V",
        normalized_value="120V",
        evidence_ids=("ev-1",),
        candidate_reason="from oem",
    )
    c2 = EnrichmentCandidate(
        candidate_id="c-2",
        product_id="p-1",
        attribute_id="voltage",
        attribute="voltage",
        value="120V",
        normalized_value="120V",
        evidence_ids=("ev-2",),
        candidate_reason="from distributor",
    )

    conflicts = engine.detect((c1, c2), (ev1, ev2))
    assert len(conflicts) == 0


def test_conflict_engine_authoritative_source_wins() -> None:
    """OEM page (AUTHORITATIVE = 120V) vs Distributor (SECONDARY = 125V) -> OEM wins."""
    engine = ConflictEngine()
    ev_oem = EvidenceReference(
        evidence_id="ev-oem",
        source_id="src-oem",
        source_authority="AUTHORITATIVE",
        evidence_text="120 V AC",
    )
    ev_dist = EvidenceReference(
        evidence_id="ev-dist",
        source_id="src-dist",
        source_authority="SECONDARY",
        evidence_text="125 V AC",
    )
    c_oem = EnrichmentCandidate(
        candidate_id="c-oem",
        product_id="p-1",
        attribute_id="voltage",
        attribute="voltage",
        value="120V",
        normalized_value="120V",
        evidence_ids=("ev-oem",),
        candidate_reason="OEM page",
    )
    c_dist = EnrichmentCandidate(
        candidate_id="c-dist",
        product_id="p-1",
        attribute_id="voltage",
        attribute="voltage",
        value="125V",
        normalized_value="125V",
        evidence_ids=("ev-dist",),
        candidate_reason="Distributor listing",
    )

    conflicts = engine.detect((c_oem, c_dist), (ev_oem, ev_dist))
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.attribute == "voltage"
    assert conflict.resolution == ConflictResolution.AUTHORITATIVE_SOURCE_WINS
    assert conflict.recommended_value == "120V"
    assert conflict.recommended_evidence_id == "ev-oem"


def test_conflict_engine_escalate_equal_top_authorities() -> None:
    """OEM page (AUTHORITATIVE = 120V) vs OEM datasheet (AUTHORITATIVE = 125V) -> ESCALATE."""
    engine = ConflictEngine()
    ev1 = EvidenceReference(
        evidence_id="ev-page",
        source_id="src-page",
        source_authority="AUTHORITATIVE",
        evidence_text="Input: 120V",
    )
    ev2 = EvidenceReference(
        evidence_id="ev-pdf",
        source_id="src-pdf",
        source_authority="AUTHORITATIVE",
        evidence_text="Rated: 125V",
    )
    c1 = EnrichmentCandidate(
        candidate_id="c-1",
        product_id="p-1",
        attribute_id="voltage",
        attribute="voltage",
        value="120V",
        normalized_value="120V",
        evidence_ids=("ev-page",),
        candidate_reason="OEM page",
    )
    c2 = EnrichmentCandidate(
        candidate_id="c-2",
        product_id="p-1",
        attribute_id="voltage",
        attribute="voltage",
        value="125V",
        normalized_value="125V",
        evidence_ids=("ev-pdf",),
        candidate_reason="OEM PDF",
    )

    conflicts = engine.detect((c1, c2), (ev1, ev2))
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.resolution == ConflictResolution.ESCALATE_TO_STRONG_MODEL
    assert conflict.recommended_value is None


def test_conflict_engine_review_required_for_equal_secondary_sources() -> None:
    """Distributor 1 (SECONDARY = 10 A) vs Distributor 2 (SECONDARY = 15 A) -> REVIEW_REQUIRED."""
    engine = ConflictEngine()
    ev1 = EvidenceReference(
        evidence_id="ev-d1",
        source_id="src-d1",
        source_authority="SECONDARY",
        evidence_text="Amps: 10 A",
    )
    ev2 = EvidenceReference(
        evidence_id="ev-d2",
        source_id="src-d2",
        source_authority="SECONDARY",
        evidence_text="Amps: 15 A",
    )
    c1 = EnrichmentCandidate(
        candidate_id="c-1",
        product_id="p-1",
        attribute_id="amperage",
        attribute="amperage",
        value="10 A",
        normalized_value="10 A",
        evidence_ids=("ev-d1",),
        candidate_reason="distributor 1",
    )
    c2 = EnrichmentCandidate(
        candidate_id="c-2",
        product_id="p-1",
        attribute_id="amperage",
        attribute="amperage",
        value="15 A",
        normalized_value="15 A",
        evidence_ids=("ev-d2",),
        candidate_reason="distributor 2",
    )

    conflicts = engine.detect((c1, c2), (ev1, ev2))
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.resolution == ConflictResolution.REVIEW_REQUIRED
    assert conflict.recommended_value is None
