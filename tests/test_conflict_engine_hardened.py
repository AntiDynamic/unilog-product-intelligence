"""Unit tests for hardened ConflictEngine and ConflictEscalationResult."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from unilog_product_intelligence.domain.conflict_escalation import ConflictEscalationResult
from unilog_product_intelligence.domain.conflicts import ConflictResolution, EvidenceConflict
from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.domain.truth import SourceAuthority
from unilog_product_intelligence.enrichment.conflicts import ConflictEngine
from unilog_product_intelligence.enrichment.models import EvidenceReference
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse


class MockRouter(LLMProvider):
    def __init__(self, response_text: str, model_name: str = "gemini-pro-test") -> None:
        self._response_text = response_text
        self._model_name = model_name

    @property
    def model(self) -> str:
        return self._model_name

    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(output_text=self._response_text, model=self._model_name)

    def generate_with_strong_model(self, request: LLMRequest) -> LLMResponse:
        return self.generate(request)


def _make_packet_with_evidence(*evidence_ids: str) -> ProductEvidencePacket:
    refs = tuple(
        EvidenceReference(evidence_id=eid, source_id="src-1", evidence_text=f"quote for {eid}")
        for eid in evidence_ids
    )
    return ProductEvidencePacket(
        product_id="p-conflict",
        mpn="M18-TEST",
        manufacturer="Milwaukee",
        evidence=refs,
    )


def test_conflict_escalation_result_invariants() -> None:
    # Valid selection within supporting IDs
    res = ConflictEscalationResult(
        attribute="voltage",
        selected_evidence_id="ev-1",
        selected_value="120V",
        reasoning="Datasheet is more specific",
        model_name="gemini-pro",
        supporting_evidence_ids=("ev-1", "ev-2"),
    )
    assert res.selected_evidence_id == "ev-1"
    assert res.selected_value == "120V"

    # Hallucinated evidence ID raises ValidationError
    with pytest.raises(ValidationError):
        ConflictEscalationResult(
            attribute="voltage",
            selected_evidence_id="ev-HALLUCINATED",
            selected_value="999V",
            reasoning="Invented",
            model_name="gemini-pro",
            supporting_evidence_ids=("ev-1", "ev-2"),
        )


def test_conflict_escalation_result_with_nulled_selection() -> None:
    res = ConflictEscalationResult.with_nulled_selection(
        attribute="voltage",
        reasoning="Could not determine truth",
        model_name="gemini-pro",
        supporting_evidence_ids=("ev-1", "ev-2"),
    )
    assert res.selected_evidence_id is None
    assert res.selected_value is None
    assert "Could not determine" in res.reasoning


def test_resolve_with_packet_verification() -> None:
    engine = ConflictEngine()
    conflict = EvidenceConflict(
        attribute="voltage",
        values=("120V", "12V"),
        evidence_ids=("ev-1", "ev-2"),
        source_authorities=(SourceAuthority.AUTHORITATIVE, SourceAuthority.SECONDARY),
    )

    # Packet has ev-1: resolves to AUTHORITATIVE_SOURCE_WINS
    packet_valid = _make_packet_with_evidence("ev-1", "ev-2")
    res_valid = engine.resolve(conflict, packet=packet_valid)
    assert res_valid.resolution == ConflictResolution.AUTHORITATIVE_SOURCE_WINS
    assert res_valid.recommended_value == "120V"
    assert res_valid.recommended_evidence_id == "ev-1"

    # Packet is missing ev-1: falls back to REVIEW_REQUIRED
    packet_missing = _make_packet_with_evidence("ev-99")
    res_missing = engine.resolve(conflict, packet=packet_missing)
    assert res_missing.resolution == ConflictResolution.REVIEW_REQUIRED
    assert res_missing.recommended_value is None


def test_escalate_valid_selection() -> None:
    engine = ConflictEngine()
    conflict = EvidenceConflict(
        attribute="voltage",
        values=("120V", "125V"),
        evidence_ids=("ev-page", "ev-pdf"),
        source_authorities=(SourceAuthority.AUTHORITATIVE, SourceAuthority.AUTHORITATIVE),
        resolution=ConflictResolution.ESCALATE_TO_STRONG_MODEL,
    )
    packet = _make_packet_with_evidence("ev-page", "ev-pdf")
    router = MockRouter(
        json.dumps(
            {
                "selected_evidence_id": "ev-pdf",
                "reasoning": "PDF spec sheet takes precedence over marketing page",
            }
        )
    )

    result = engine.escalate(conflict, packet, router)
    assert result.selected_evidence_id == "ev-pdf"
    assert result.selected_value == "125V"
    assert "PDF spec sheet" in result.reasoning

    # Apply escalation
    updated_conflict = engine.apply_escalation(conflict, result)
    assert updated_conflict.resolution == ConflictResolution.AUTHORITATIVE_SOURCE_WINS
    assert updated_conflict.recommended_value == "125V"
    assert updated_conflict.recommended_evidence_id == "ev-pdf"


def test_escalate_hallucinated_selection_falls_back() -> None:
    engine = ConflictEngine()
    conflict = EvidenceConflict(
        attribute="voltage",
        values=("120V", "125V"),
        evidence_ids=("ev-page", "ev-pdf"),
        source_authorities=(SourceAuthority.AUTHORITATIVE, SourceAuthority.AUTHORITATIVE),
        resolution=ConflictResolution.ESCALATE_TO_STRONG_MODEL,
    )
    packet = _make_packet_with_evidence("ev-page", "ev-pdf")
    router = MockRouter(
        json.dumps(
            {
                "selected_evidence_id": "ev-UNSEEN",
                "reasoning": "I made this up",
            }
        )
    )

    result = engine.escalate(conflict, packet, router)
    assert result.selected_evidence_id is None
    assert result.selected_value is None
    assert "invalid or unverified" in result.reasoning

    # Apply escalation to conflict -> REVIEW_REQUIRED
    updated_conflict = engine.apply_escalation(conflict, result)
    assert updated_conflict.resolution == ConflictResolution.REVIEW_REQUIRED
    assert updated_conflict.recommended_value is None


def test_escalate_router_exception_handled() -> None:
    engine = ConflictEngine()
    conflict = EvidenceConflict(
        attribute="voltage",
        values=("120V", "125V"),
        evidence_ids=("ev-page", "ev-pdf"),
        source_authorities=(SourceAuthority.AUTHORITATIVE, SourceAuthority.AUTHORITATIVE),
    )
    packet = _make_packet_with_evidence("ev-page", "ev-pdf")

    class CrashingRouter(LLMProvider):
        def generate(self, request: LLMRequest) -> LLMResponse:
            raise RuntimeError("API connection timeout")

    result = engine.escalate(conflict, packet, CrashingRouter())
    assert result.selected_evidence_id is None
    assert "API connection timeout" in result.reasoning
