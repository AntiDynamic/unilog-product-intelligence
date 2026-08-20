"""Deterministic evidence support verification for attribute proposals.

Verifies that the text in cited EvidenceReference records mechanically supports
the proposed value before the candidate is accepted into ProductTruth.

Zero LLM calls — 100% deterministic, token- and numeric-aware matching.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from unilog_product_intelligence.enrichment.models import EvidenceReference


@dataclass(frozen=True)
class EvidenceSupportResult:
    """Result of checking whether evidence text supports an attribute proposal."""

    supported: bool
    reason: str | None = None
    matched_snippet: str | None = None


class EvidenceSupportValidator:
    """Mechanically checks whether evidence text supports a proposed attribute value.

    Verification Strategies:
      1. Direct Substring / Token Containment:
         Checks if the normalized value string or its essential tokens exist in the evidence.
      2. Numeric & Unit Matching:
         Extracts numbers and checks if proposed numbers actually appear in the snippet.
         Rejects value hallucinations where the number differs (e.g. 24V proposed on 18V text).
      3. Range Matching:
         Matches range bounds (e.g. '0-550 / 0-2,000 RPM').
      4. Negation & Contradiction Guard:
         Detects direct contradictions like 'corded' vs 'cordless' or 'brushless' vs 'brushed'.
    """

    # Common antonyms / contradiction pairs
    _CONTRADICTIONS: tuple[tuple[str, str], ...] = (
        ("corded", "cordless"),
        ("brushless", "brushed"),
        ("indoor", "outdoor"),
        ("included", "not included"),
        ("yes", "no"),
        ("true", "false"),
    )

    def _normalize(self, text: str) -> str:
        """Lowercases and normalizes whitespace, units, and punctuation for token comparison."""
        spaced = re.sub(r"(\d+)([A-Za-z]+)", r"\1 \2", text)
        cleaned = re.sub(r"[^\w\s\.\-\/\:]", " ", spaced.casefold())
        return " ".join(cleaned.split())

    def _extract_numbers(self, text: str) -> list[str]:
        """Extract all numeric tokens including decimals and fractions."""
        spaced = re.sub(r"(\d+)([A-Za-z]+)", r"\1 \2", text)
        cleaned = re.sub(r",(\d{3})", r"\1", spaced)
        raw_matches = re.findall(r"(?<![\w\.])\d+(?:\.\d+)?(?:\/\d+)?(?![\w\.])", cleaned)
        return [m.strip() for m in raw_matches if m.strip()]

    def _check_contradictions(self, proposed_val: str, evidence_text: str) -> str | None:
        """Return a reason string if an explicit contradiction is detected."""
        norm_prop = self._normalize(proposed_val)
        norm_ev = self._normalize(evidence_text)

        for word_a, word_b in self._CONTRADICTIONS:
            # If proposal asserts word_a, but evidence explicitly has word_b and NOT word_a
            if (
                re.search(rf"\b{word_a}\b", norm_prop)
                and not re.search(rf"\b{word_a}\b", norm_ev)
                and re.search(rf"\b{word_b}\b", norm_ev)
            ):
                return (
                    f"Contradiction detected: proposal asserts '{word_a}' "
                    f"but evidence states '{word_b}'"
                )
            # Symmetric check
            if (
                re.search(rf"\b{word_b}\b", norm_prop)
                and not re.search(rf"\b{word_b}\b", norm_ev)
                and re.search(rf"\b{word_a}\b", norm_ev)
            ):
                return (
                    f"Contradiction detected: proposal asserts '{word_b}' "
                    f"but evidence states '{word_a}'"
                )
        return None

    def supports(
        self,
        attribute: str,
        proposed_value: Any,
        evidence: Sequence[EvidenceReference] | EvidenceReference,
        uom: str | None = None,
    ) -> EvidenceSupportResult:
        """Check whether one or more evidence records support the proposed value.

        Parameters
        ----------
        attribute:
            The canonical attribute name.
        proposed_value:
            The value proposed by the model.
        evidence:
            One or more EvidenceReference records cited by the proposal.
        uom:
            Optional unit of measure.

        Returns
        -------
        EvidenceSupportResult
            supported=True if evidence text mechanically supports the value; False otherwise.
        """
        if proposed_value is None or str(proposed_value).strip() == "":
            return EvidenceSupportResult(supported=False, reason="Proposed value is empty")

        ev_list = [evidence] if isinstance(evidence, EvidenceReference) else list(evidence)
        if not ev_list:
            return EvidenceSupportResult(supported=False, reason="No evidence references provided")

        val_str = str(proposed_value).strip()
        combined_val = f"{val_str} {uom}".strip() if uom else val_str
        norm_val = self._normalize(val_str)
        val_numbers = self._extract_numbers(val_str)

        # Check each evidence record
        for ref in ev_list:
            ev_text = getattr(ref, "evidence_text", "") or ""
            if not ev_text.strip():
                continue

            norm_ev = self._normalize(ev_text)

            # 1. Contradiction check
            contra = self._check_contradictions(combined_val, ev_text)
            if contra:
                return EvidenceSupportResult(
                    supported=False, reason=contra, matched_snippet=ev_text
                )

            # 2. Exact or normalized substring match
            if val_str.casefold() in ev_text.casefold() or norm_val in norm_ev:
                return EvidenceSupportResult(supported=True, matched_snippet=ev_text)

            # 3. Numeric verification
            if val_numbers:
                ev_numbers = set(self._extract_numbers(ev_text))
                # All proposed numbers must appear in the evidence snippet
                if all(num in ev_numbers for num in val_numbers):
                    return EvidenceSupportResult(supported=True, matched_snippet=ev_text)
                else:
                    # Number mismatch
                    missing_nums = [num for num in val_numbers if num not in ev_numbers]
                    return EvidenceSupportResult(
                        supported=False,
                        reason=(
                            f"Numeric value mismatch: proposed number(s) {missing_nums} "
                            "not found in evidence"
                        ),
                        matched_snippet=ev_text,
                    )

            # 4. Token-level containment (for multi-word categorical strings)
            val_tokens = [t for t in norm_val.split() if len(t) > 2]
            if val_tokens and all(t in norm_ev for t in val_tokens):
                return EvidenceSupportResult(supported=True, matched_snippet=ev_text)

        # If none of the evidence records matched
        return EvidenceSupportResult(
            supported=False,
            reason=f"Evidence text does not contain or support value '{val_str}'",
            matched_snippet=ev_list[0].evidence_text if ev_list else None,
        )


__all__ = ["EvidenceSupportResult", "EvidenceSupportValidator"]
