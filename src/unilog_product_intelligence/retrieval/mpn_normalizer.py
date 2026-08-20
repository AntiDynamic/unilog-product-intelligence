"""Generic MPN normalization and hypothesis generation for industrial retrieval.

Industrial suppliers and distributors frequently modify OEM part numbers by:
  - Prepending distributor / vendor codes (e.g., '3MABR-7100075678' -> '7100075678')
  - Stripping or adding hyphens/separators (e.g., '49-94-0013' <-> '49940013')
  - Appending packaging or lot suffixes (e.g., '-BOX', '-PKG10', '06G')
  - Embedding manufacturer internal item IDs

Conceptual Ranking & Identity Model:
  1. RAW_EXACT: Exact raw MPN (conf: 1.0, is_lossless: True, identity_eligible: True)
  2. LOSSLESS_NORMALIZED: Pure punctuation/separator variation
     (conf: 0.98, is_lossless: True, identity_eligible: True)
  3. VERIFIED_MANUFACTURER_TRANSFORM: Explicit manufacturer-specific rule
     (conf: 0.90, is_lossless: False, identity_eligible: True)
  4. EXPLORATORY_HYPOTHESIS: Generic regex prefix strip or numeric extraction
     (conf: 0.35-0.50, is_lossless: False, identity_eligible: False - SEARCH ONLY)
  5. NO_MATCH: Not found
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class MpnHypothesisType(StrEnum):
    RAW = "raw"
    LOSSLESS_NORMALIZED = "lossless_normalized"
    VERIFIED_MANUFACTURER_TRANSFORM = "verified_manufacturer_transform"
    EXPLORATORY_PREFIX_STRIP = "exploratory_prefix_strip"
    EXPLORATORY_NUMERIC_EXTRACTION = "exploratory_numeric_extraction"
    EXPLORATORY_COMPACT = "exploratory_compact"
    # Legacy alias support for backward compatibility
    STRIPPED_DISTRIBUTOR_PREFIX = "stripped_distributor_prefix"
    NUMERIC_CORE_ID = "numeric_core_id"
    ALPHANUMERIC_COMPACT = "alphanumeric_compact"


@dataclass(frozen=True)
class MpnHypothesis:
    value: str
    hypothesis_type: MpnHypothesisType
    confidence: float
    is_lossless: bool = False
    identity_eligible: bool = False
    transformation_rule: str | None = None

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError("MpnHypothesis value cannot be empty.")


class MpnNormalizer:
    """Generate ranked MPN hypotheses from raw supplier input strings.

    Distinguishes search-eligible hypotheses from identity-eligible hypotheses.
    """

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
            Optional manufacturer/brand name to apply domain-specific verified rules.

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

        def add_hypothesis(
            val: str,
            h_type: MpnHypothesisType,
            conf: float,
            *,
            is_lossless: bool = False,
            identity_eligible: bool = False,
            rule: str | None = None,
        ) -> None:
            v_trimmed = val.strip()
            key = v_trimmed.casefold()
            if v_trimmed and key not in seen_values:
                seen_values.add(key)
                hypotheses.append(
                    MpnHypothesis(
                        value=v_trimmed,
                        hypothesis_type=h_type,
                        confidence=conf,
                        is_lossless=is_lossless,
                        identity_eligible=identity_eligible,
                        transformation_rule=rule,
                    )
                )

        # 1. Exact raw MPN is always highest confidence identity candidate
        add_hypothesis(
            cleaned_raw,
            MpnHypothesisType.RAW,
            1.0,
            is_lossless=True,
            identity_eligible=True,
            rule="raw_input",
        )

        # 2. Lossless alphanumeric compact version (e.g. '49-94-0013' -> '49940013')
        if any(c in cleaned_raw for c in ("-", "_", " ", "/", ".")):
            compact = re.sub(r"[-_\s/.]+", "", cleaned_raw)
            if len(compact) >= 3 and compact != cleaned_raw:
                add_hypothesis(
                    compact,
                    MpnHypothesisType.LOSSLESS_NORMALIZED,
                    0.98,
                    is_lossless=True,
                    identity_eligible=True,
                    rule="lossless_separator_removal",
                )

        # Check for verified manufacturer-specific transformations
        mfg_lower = (manufacturer_hint or "").casefold()
        is_3m_manufacturer = any(k in mfg_lower for k in ("3m", "jam industrial"))

        # 3. Stripped distributor prefix (e.g. 3MABR-7100075678 -> 7100075678)
        match_prefix = self._DISTRIBUTOR_PREFIX_PATTERN.match(cleaned_raw)
        if match_prefix:
            stripped = match_prefix.group(1).strip()
            if len(stripped) >= 3:
                prefix = cleaned_raw[: match_prefix.start(1)].rstrip("-_").upper()
                is_known_prefix = (prefix.startswith("3M") and is_3m_manufacturer) or (
                    is_3m_manufacturer and re.match(r"^\d{8,10}$", stripped)
                )

                if is_known_prefix:
                    add_hypothesis(
                        stripped,
                        MpnHypothesisType.VERIFIED_MANUFACTURER_TRANSFORM,
                        0.90,
                        is_lossless=False,
                        identity_eligible=True,
                        rule="known_3m_distributor_prefix",
                    )
                else:
                    # Generic prefix strip is exploratory only (searchable, cannot verify identity)
                    add_hypothesis(
                        stripped,
                        MpnHypothesisType.EXPLORATORY_PREFIX_STRIP,
                        0.50,
                        is_lossless=False,
                        identity_eligible=False,
                        rule="generic_prefix_strip",
                    )

        # 4. Industrial 8-10 digit numeric core (e.g. 3M item IDs like 7100075678)
        numeric_matches = self._NUMERIC_CORE_PATTERN.findall(cleaned_raw)
        for num in numeric_matches:
            if is_3m_manufacturer:
                add_hypothesis(
                    num,
                    MpnHypothesisType.VERIFIED_MANUFACTURER_TRANSFORM,
                    0.90,
                    is_lossless=False,
                    identity_eligible=True,
                    rule="known_3m_numeric_id",
                )
            else:
                add_hypothesis(
                    num,
                    MpnHypothesisType.EXPLORATORY_NUMERIC_EXTRACTION,
                    0.40,
                    is_lossless=False,
                    identity_eligible=False,
                    rule="generic_numeric_core",
                )

        # 5. For stripped prefix, also generate its alphanumeric compact version (exploratory)
        if match_prefix:
            stripped = match_prefix.group(1).strip()
            if any(c in stripped for c in ("-", "_", " ", "/", ".")):
                compact_stripped = re.sub(r"[-_\s/.]+", "", stripped)
                if len(compact_stripped) >= 3:
                    add_hypothesis(
                        compact_stripped,
                        MpnHypothesisType.EXPLORATORY_COMPACT,
                        0.35,
                        is_lossless=False,
                        identity_eligible=False,
                        rule="exploratory_compact",
                    )

        return hypotheses
