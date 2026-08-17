"""Generic MPN normalization and hypothesis generation for industrial retrieval.

Industrial suppliers and distributors frequently modify OEM part numbers by:
  - Prepending distributor / vendor codes (e.g., '3MABR-7100075678' -> '7100075678')
  - Stripping or adding hyphens (e.g., '49-94-0013' <-> '49940013')
  - Appending packaging or lot suffixes (e.g., '-BOX', '-PKG10', '06G')
  - Embedding manufacturer internal item IDs

This module generates ranked MPN hypotheses. Every hypothesis must be verified
against an authoritative manufacturer source before being accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class MpnHypothesisType(StrEnum):
    RAW = "raw"
    STRIPPED_DISTRIBUTOR_PREFIX = "stripped_distributor_prefix"
    NUMERIC_CORE_ID = "numeric_core_id"
    ALPHANUMERIC_COMPACT = "alphanumeric_compact"
    CLEANED_SPECIAL_CHARS = "cleaned_special_chars"


@dataclass(frozen=True)
class MpnHypothesis:
    value: str
    hypothesis_type: MpnHypothesisType
    confidence: float

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError("MpnHypothesis value cannot be empty.")


class MpnNormalizer:
    """Generate ranked MPN hypotheses from raw supplier input strings."""

    # Generic distributor prefix pattern: 2 to 6 uppercase/digit chars followed by hyphen/underscore
    _DISTRIBUTOR_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9]{2,6}[-_]([A-Za-z0-9._/-]+)$")

    # 3M and industrial 8-10 digit numeric item identifier pattern
    _NUMERIC_CORE_PATTERN = re.compile(r"\b(\d{8,10})\b")

    def normalize(
        self,
        raw_mpn: str | None,
        manufacturer_hint: str | None = None,
    ) -> list[MpnHypothesis]:
        """Generate ranked candidate MPN variants to test against manufacturer sources.

        Parameters
        ----------
        raw_mpn:
            Raw MPN string from the input file (e.g., '3MABR-7100075678', '49-94-0013').
        manufacturer_hint:
            Optional manufacturer name to apply domain-specific heuristics.

        Returns
        -------
        Ordered list of MpnHypothesis objects, deduplicated by hypothesis value.
        """
        if not raw_mpn:
            return []

        cleaned_raw = raw_mpn.strip()
        if not cleaned_raw:
            return []

        hypotheses: list[MpnHypothesis] = []
        seen_values: set[str] = set()

        def add_hypothesis(val: str, h_type: MpnHypothesisType, conf: float) -> None:
            v_trimmed = val.strip()
            # Normalize casefold for deduplication, but keep original case
            key = v_trimmed.casefold()
            if v_trimmed and key not in seen_values:
                seen_values.add(key)
                hypotheses.append(
                    MpnHypothesis(value=v_trimmed, hypothesis_type=h_type, confidence=conf)
                )

        # 1. Exact raw MPN is always highest confidence candidate
        add_hypothesis(cleaned_raw, MpnHypothesisType.RAW, 1.0)

        # 2. Stripped distributor prefix (e.g. 3MABR-7100075678 -> 7100075678)
        match_prefix = self._DISTRIBUTOR_PREFIX_PATTERN.match(cleaned_raw)
        if match_prefix:
            stripped = match_prefix.group(1).strip()
            if len(stripped) >= 3:
                add_hypothesis(stripped, MpnHypothesisType.STRIPPED_DISTRIBUTOR_PREFIX, 0.95)

        # 3. Industrial 8-10 digit numeric core (e.g. 3M item IDs like 7100075678)
        numeric_matches = self._NUMERIC_CORE_PATTERN.findall(cleaned_raw)
        for num in numeric_matches:
            add_hypothesis(num, MpnHypothesisType.NUMERIC_CORE_ID, 0.95)

        # 4. Alphanumeric compact version without hyphens/spaces (e.g. '49-94-0013' -> '49940013')
        if any(c in cleaned_raw for c in ("-", "_", " ", "/", ".")):
            compact = re.sub(r"[-_\s/.]+", "", cleaned_raw)
            if len(compact) >= 3 and compact != cleaned_raw:
                add_hypothesis(compact, MpnHypothesisType.ALPHANUMERIC_COMPACT, 0.85)

        # 5. For stripped prefix, also generate its alphanumeric compact version
        if match_prefix:
            stripped = match_prefix.group(1).strip()
            if any(c in stripped for c in ("-", "_", " ", "/", ".")):
                compact_stripped = re.sub(r"[-_\s/.]+", "", stripped)
                if len(compact_stripped) >= 3:
                    add_hypothesis(compact_stripped, MpnHypothesisType.ALPHANUMERIC_COMPACT, 0.80)

        return hypotheses
