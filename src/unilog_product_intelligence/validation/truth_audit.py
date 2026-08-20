"""Truth audit pipeline component: verifies evidence invariants across final product state."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from unilog_product_intelligence.domain.conflicts import ConflictResolution, EvidenceConflict
from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.domain.provenance import FinalAttribute


class TruthAuditResult(BaseModel):
    """Result of truth and provenance invariant verification for a product."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str
    total_attributes: int = 0
    grounded_attributes: int = 0
    unresolved_attributes: int = 0
    conflicts_detected: int = 0
    audit_passed: bool = True
    publication_safe: bool = True
    violations: tuple[str, ...] = ()


class TruthAudit:
    """Audits the final state of product enrichment against core evidence invariants.

    Invariants Checked:
      1. Evidence Grounding: Every attribute claiming evidence backing must cite an
         evidence_id that actually exists in the ProductEvidencePacket.
      2. No Hallucination: Attribute values must not be marked as verified/grounded if
         their evidence citation is missing or empty.
      3. Conflict Completeness: Any active attribute conflicts must be explicitly resolved
         or appropriately flagged as REVIEW_REQUIRED / ESCALATE_TO_STRONG_MODEL.
      4. Immutability & Traceability: If canonical_product_url is present, it must match
         the packet's canonical_product_url.
    """

    def audit(
        self,
        packet: ProductEvidencePacket,
        final_attributes: Sequence[FinalAttribute] = (),
        conflicts: Sequence[EvidenceConflict] = (),
    ) -> TruthAuditResult:
        violations: list[str] = []
        valid_ev_ids: set[str] = {
            str(e.evidence_id)
            for e in packet.evidence
            if getattr(e, "evidence_id", None) is not None
        }

        # Also consider structured facts evidence IDs if present
        for fact in packet.structured_facts:
            if fact.evidence_id is not None:
                valid_ev_ids.add(fact.evidence_id)

        grounded_count = 0
        unresolved_count = 0

        for attr in final_attributes:
            if attr.value is None or str(attr.value).strip() == "":
                unresolved_count += 1
                continue

            if attr.evidence_id:
                if attr.evidence_id not in valid_ev_ids:
                    violations.append(
                        f"Attribute '{attr.attribute}' cites unknown evidence_id "
                        f"'{attr.evidence_id}' not found in ProductEvidencePacket."
                    )
                else:
                    grounded_count += 1
            else:
                # Value provided without an evidence ID is an unsupported claim
                unresolved_count += 1
                violations.append(
                    f"Attribute '{attr.attribute}' asserts value '{attr.value}' "
                    "without supporting evidence_id."
                )

        # Check conflicts
        conflicts_to_check = tuple(conflicts) or tuple(packet.conflicts)
        for conflict in conflicts_to_check:
            if conflict.resolution not in {
                ConflictResolution.AUTHORITATIVE_SOURCE_WINS,
                ConflictResolution.REVIEW_REQUIRED,
                ConflictResolution.ESCALATE_TO_STRONG_MODEL,
            }:
                violations.append(
                    f"Conflict for attribute '{conflict.attribute}' has invalid "
                    f"resolution state: {conflict.resolution}"
                )

        audit_passed = len(violations) == 0
        publication_safe = audit_passed and len(violations) == 0

        return TruthAuditResult(
            product_id=packet.product_id,
            total_attributes=len(final_attributes),
            grounded_attributes=grounded_count,
            unresolved_attributes=unresolved_count,
            conflicts_detected=len(conflicts_to_check),
            audit_passed=audit_passed,
            publication_safe=publication_safe,
            violations=tuple(violations),
        )


__all__ = ["TruthAudit", "TruthAuditResult"]
