"""Conflict detection and resolution engine across multi-source evidence candidates."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from unilog_product_intelligence.domain.conflict_escalation import ConflictEscalationResult
from unilog_product_intelligence.domain.conflicts import ConflictResolution, EvidenceConflict
from unilog_product_intelligence.domain.evidence_packet import ProductEvidencePacket
from unilog_product_intelligence.domain.truth import SourceAuthority
from unilog_product_intelligence.enrichment.models import EnrichmentCandidate, EvidenceReference
from unilog_product_intelligence.providers.base import LLMRequest


class ConflictEngine:
    """Detects and resolves attribute value disagreements across evidence candidates.

    Authority Hierarchy:
      AUTHORITATIVE (0) > HIGH (1) > MEDIUM (2) > SECONDARY (3) > LOW (4) > UNKNOWN (5)

    Resolution Policy:
      - If one candidate has strictly higher source authority than all competitors:
        → AUTHORITATIVE_SOURCE_WINS (the higher-authority value is recommended).
      - If multiple candidates share the highest authority (e.g. OEM page vs OEM datasheet)
        and present distinct normalized values:
        → ESCALATE_TO_STRONG_MODEL (if escalation available) or REVIEW_REQUIRED.
      - If secondary or unverified sources conflict:
        → REVIEW_REQUIRED.
    """

    _AUTHORITY_RANK: dict[SourceAuthority, int] = {
        SourceAuthority.AUTHORITATIVE: 0,
        SourceAuthority.HIGH: 1,
        SourceAuthority.MEDIUM: 2,
        SourceAuthority.SECONDARY: 3,
        SourceAuthority.LOW: 4,
        SourceAuthority.UNKNOWN: 5,
    }

    def _parse_authority(self, auth_str: str | SourceAuthority | None) -> SourceAuthority:
        if isinstance(auth_str, SourceAuthority):
            return auth_str
        if not auth_str:
            return SourceAuthority.UNKNOWN
        try:
            return SourceAuthority(str(auth_str).casefold())
        except ValueError:
            # Map common string representations
            upper = str(auth_str).upper()
            if upper == "AUTHORITATIVE":
                return SourceAuthority.AUTHORITATIVE
            if upper == "HIGH":
                return SourceAuthority.HIGH
            if upper == "MEDIUM":
                return SourceAuthority.MEDIUM
            if upper == "SECONDARY":
                return SourceAuthority.SECONDARY
            if upper == "LOW":
                return SourceAuthority.LOW
            return SourceAuthority.UNKNOWN

    def detect(
        self,
        candidates: tuple[EnrichmentCandidate, ...] | list[EnrichmentCandidate],
        evidence: tuple[EvidenceReference, ...] | list[EvidenceReference] = (),
    ) -> tuple[EvidenceConflict, ...]:
        """Group candidates by attribute and detect disagreements across distinct values."""
        evidence_by_id: dict[str, EvidenceReference] = {
            e.evidence_id: e for e in evidence if getattr(e, "evidence_id", None)
        }

        # Also collect evidence attached directly to candidates
        for c in candidates:
            for ev in getattr(c, "evidence", ()) or ():
                if getattr(ev, "evidence_id", None):
                    evidence_by_id[ev.evidence_id] = ev

        by_attribute: dict[str, list[EnrichmentCandidate]] = defaultdict(list)
        for c in candidates:
            attr_name = (
                getattr(c, "attribute", None)
                or getattr(c, "attribute_id", None)
                or ""
            ).casefold().strip()
            if attr_name:
                by_attribute[attr_name].append(c)

        conflicts: list[EvidenceConflict] = []

        for attr, group in by_attribute.items():
            if len(group) < 2:
                continue

            # Check for distinct normalized or raw values
            value_to_candidates: dict[str, list[EnrichmentCandidate]] = defaultdict(list)
            for c in group:
                val_str = str(c.normalized_value or c.raw_value or c.value or "").strip()
                if val_str:
                    value_to_candidates[val_str.casefold()].append(c)

            if len(value_to_candidates) < 2:
                # All candidates agree on the same value — no conflict
                continue

            # We have a disagreement across 2+ distinct values
            distinct_values: list[str] = []
            distinct_ev_ids: list[str] = []
            distinct_authorities: list[SourceAuthority] = []

            for val_key, val_cands in value_to_candidates.items():
                first_cand = val_cands[0]
                val_repr = str(
                    first_cand.normalized_value
                    or first_cand.raw_value
                    or first_cand.value
                    or ""
                ).strip()
                distinct_values.append(val_repr)

                # Find best evidence_id and authority for this value group
                best_ev_id = (
                    first_cand.evidence_ids[0]
                    if first_cand.evidence_ids
                    else f"ev-cand-{first_cand.candidate_id}"
                )
                distinct_ev_ids.append(best_ev_id)

                # Determine source authority
                ev_obj = evidence_by_id.get(best_ev_id)
                auth_raw = getattr(ev_obj, "source_authority", None) if ev_obj else None
                auth = self._parse_authority(auth_raw)
                distinct_authorities.append(auth)

            raw_conflict = EvidenceConflict(
                attribute=attr,
                values=tuple(distinct_values),
                evidence_ids=tuple(distinct_ev_ids),
                source_authorities=tuple(distinct_authorities),
                resolution=ConflictResolution.REVIEW_REQUIRED,
            )
            resolved_conflict = self.resolve(raw_conflict)
            conflicts.append(resolved_conflict)

        return tuple(conflicts)

    def resolve(
        self,
        conflict: EvidenceConflict,
        packet: ProductEvidencePacket | None = None,
    ) -> EvidenceConflict:
        """Resolve a conflict based on source authority hierarchy, optionally verified against packet."""
        if len(conflict.values) < 2:
            return conflict

        # Pair each value with its authority rank
        ranks = [
            (
                self._AUTHORITY_RANK.get(
                    auth, self._AUTHORITY_RANK[SourceAuthority.UNKNOWN]
                ),
                idx,
                conflict.values[idx],
                conflict.evidence_ids[idx] if idx < len(conflict.evidence_ids) else None,
                auth,
            )
            for idx, auth in enumerate(conflict.source_authorities)
        ]

        if not ranks:
            return conflict

        # Sort by authority rank ascending (0 is highest authority)
        ranks.sort(key=lambda r: r[0])

        best_rank, best_idx, best_val, best_ev_id, best_auth = ranks[0]
        second_rank = ranks[1][0]

        if best_rank < second_rank:
            # If packet is supplied, verify recommended evidence_id exists in packet
            if packet is not None and packet.evidence:
                packet_ev_ids = {
                    getattr(e, "evidence_id", None)
                    for e in packet.evidence
                    if getattr(e, "evidence_id", None)
                }
                if best_ev_id not in packet_ev_ids:
                    return conflict.model_copy(
                        update={
                            "recommended_value": None,
                            "recommended_evidence_id": None,
                            "resolution": ConflictResolution.REVIEW_REQUIRED,
                        }
                    )

            # Strictly higher authority wins automatically
            return conflict.model_copy(
                update={
                    "recommended_value": best_val,
                    "recommended_evidence_id": best_ev_id,
                    "resolution": ConflictResolution.AUTHORITATIVE_SOURCE_WINS,
                }
            )

        # Equal top authority (e.g. two AUTHORITATIVE sources disagree)
        if best_rank in {
            self._AUTHORITY_RANK[SourceAuthority.AUTHORITATIVE],
            self._AUTHORITY_RANK[SourceAuthority.HIGH],
        }:
            return conflict.model_copy(
                update={
                    "recommended_value": None,
                    "recommended_evidence_id": None,
                    "resolution": ConflictResolution.ESCALATE_TO_STRONG_MODEL,
                }
            )

        # Lower equal authorities -> REVIEW_REQUIRED
        return conflict.model_copy(
            update={
                "recommended_value": None,
                "recommended_evidence_id": None,
                "resolution": ConflictResolution.REVIEW_REQUIRED,
            }
        )

    def escalate(
        self,
        conflict: EvidenceConflict,
        packet: ProductEvidencePacket,
        router: Any,
    ) -> ConflictEscalationResult:
        """Escalate an equal-authority conflict to a strong model.

        Gemini selects between existing evidence records — it does not create evidence.
        """
        valid_ev_ids = set(conflict.evidence_ids)
        if packet.evidence:
            packet_ids = {
                getattr(e, "evidence_id", None)
                for e in packet.evidence
                if getattr(e, "evidence_id", None)
            }
            valid_ev_ids = valid_ev_ids & packet_ids

        model_name = getattr(router, "model", "strong-model")

        # Build prompt listing the conflicting options and evidence
        options_text = []
        ev_to_val: dict[str, str] = {}
        for idx, ev_id in enumerate(conflict.evidence_ids):
            val = conflict.values[idx] if idx < len(conflict.values) else ""
            ev_to_val[ev_id] = val
            options_text.append(f"- Evidence ID: {ev_id} | Value: {val}")

        prompt = (
            f"You are resolving an attribute conflict for attribute '{conflict.attribute}'.\n"
            f"Product: {packet.manufacturer or ''} {packet.mpn or ''}\n\n"
            "Conflicting Evidence Options:\n"
            + "\n".join(options_text)
            + "\n\nSelect the single most accurate evidence ID from the options above.\n"
            "Respond ONLY with a JSON object: "
            '{"selected_evidence_id": "<id>", "reasoning": "<reason>"}'
        )

        try:
            req = LLMRequest(
                task="conflict_escalation",
                input_text=prompt,
            )
            if hasattr(router, "generate_with_strong_model"):
                resp = router.generate_with_strong_model(req)
            elif hasattr(router, "generate"):
                resp = router.generate(req)
            else:
                resp = router(prompt)

            content = getattr(resp, "output_text", getattr(resp, "content", str(resp)))
            parsed = json.loads(content) if isinstance(content, str) and content.strip().startswith("{") else {}
            selected_id = parsed.get("selected_evidence_id")
            reasoning = parsed.get("reasoning", "Escalation model selected option.")

            if selected_id and selected_id in valid_ev_ids:
                selected_val = ev_to_val.get(selected_id)
                return ConflictEscalationResult(
                    attribute=conflict.attribute,
                    selected_evidence_id=selected_id,
                    selected_value=selected_val,
                    reasoning=reasoning,
                    model_name=model_name,
                    supporting_evidence_ids=conflict.evidence_ids,
                )
            else:
                return ConflictEscalationResult.with_nulled_selection(
                    attribute=conflict.attribute,
                    reasoning=f"Model returned invalid or unverified evidence ID: {selected_id}",
                    model_name=model_name,
                    supporting_evidence_ids=conflict.evidence_ids,
                )
        except Exception as exc:
            return ConflictEscalationResult.with_nulled_selection(
                attribute=conflict.attribute,
                reasoning=f"Escalation failed with error: {exc}",
                model_name=model_name,
                supporting_evidence_ids=conflict.evidence_ids,
            )

    def apply_escalation(
        self,
        conflict: EvidenceConflict,
        result: ConflictEscalationResult,
    ) -> EvidenceConflict:
        """Apply the outcome of an escalation to update the EvidenceConflict record."""
        if result.selected_evidence_id is not None:
            return conflict.model_copy(
                update={
                    "recommended_value": result.selected_value,
                    "recommended_evidence_id": result.selected_evidence_id,
                    "resolution": ConflictResolution.AUTHORITATIVE_SOURCE_WINS,
                }
            )
        return conflict.model_copy(
            update={
                "recommended_value": None,
                "recommended_evidence_id": None,
                "resolution": ConflictResolution.REVIEW_REQUIRED,
            }
        )


__all__ = ["ConflictEngine"]
