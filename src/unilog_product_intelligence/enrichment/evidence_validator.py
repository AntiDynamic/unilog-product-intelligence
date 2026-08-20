"""EvidenceConstraintValidator: reject proposals that cite missing or unknown evidence.

Every attribute proposal produced by Gemini must:
  1. Cite at least one evidence_id  (non-empty evidence_ids tuple)
  2. Every cited evidence_id must exist in the ProductEvidencePacket's evidence set

Proposals that fail either check are rejected before they can reach ProductTruth.
This enforces the invariant: AI proposals cannot introduce unsupported facts.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.enrichment.schemas import AttributeProposal


class EvidenceValidationResult(BaseModel):
    """Result of running EvidenceConstraintValidator over a set of proposals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: tuple[AttributeProposal, ...] = ()
    rejected: tuple[AttributeProposal, ...] = ()
    rejection_reasons: tuple[str, ...] = ()


class EvidenceConstraintValidator:
    """Validates that Gemini proposals cite only real, in-packet evidence IDs.

    Rules (applied in order for each proposal):
      1. If evidence_ids is empty       → reject ("missing evidence IDs")
      2. If any evidence_id is unknown  → reject ("unknown evidence IDs: ...")
      3. All IDs valid                  → accept

    This is entirely deterministic — no LLM calls are made here.
    """

    def validate(
        self,
        proposals: Sequence[AttributeProposal],
        packet: ProductEvidencePacket,
    ) -> EvidenceValidationResult:
        """Validate proposals against the evidence packet.

        Parameters
        ----------
        proposals:
            The sequence of AttributeProposal objects returned by Gemini.
        packet:
            The ProductEvidencePacket assembled by Phase 5.  The set of valid
            evidence IDs is derived from `packet.evidence`.

        Returns
        -------
        EvidenceValidationResult
            Accepted and rejected proposals with reasons for each rejection.
        """
        valid_evidence_ids: set[str] = {
            str(getattr(ref, "evidence_id"))
            for ref in packet.evidence
            if getattr(ref, "evidence_id", None) is not None
        }

        accepted: list[AttributeProposal] = []
        rejected: list[AttributeProposal] = []
        reasons: list[str] = []

        for proposal in proposals:
            if not proposal.evidence_ids:
                rejected.append(proposal)
                reasons.append(
                    f"{proposal.attribute}: missing evidence IDs — "
                    "every proposal must cite at least one evidence record"
                )
                continue

            unknown_ids = set(proposal.evidence_ids) - valid_evidence_ids
            if unknown_ids:
                rejected.append(proposal)
                reasons.append(
                    f"{proposal.attribute}: unknown evidence IDs "
                    f"{sorted(unknown_ids)} — IDs must refer to records in the packet"
                )
                continue

            accepted.append(proposal)

        return EvidenceValidationResult(
            accepted=tuple(accepted),
            rejected=tuple(rejected),
            rejection_reasons=tuple(reasons),
        )


__all__ = [
    "EvidenceConstraintValidator",
    "EvidenceValidationResult",
]
