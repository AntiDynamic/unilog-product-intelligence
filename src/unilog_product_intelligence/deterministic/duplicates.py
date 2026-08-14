"""Deterministic identity support, not semantic product merging."""

from dataclasses import dataclass
from enum import StrEnum

from .normalization import normalize_part_number


class DuplicateStatus(StrEnum):
    EXACT_DUPLICATE = "exact_duplicate"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    DISTINCT = "distinct"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class DuplicateAssessment:
    status: DuplicateStatus
    signals: tuple[str, ...]
    reason: str


def assess_duplicate(
    manufacturer_a: str | None,
    mpn_a: str | None,
    manufacturer_b: str | None,
    mpn_b: str | None,
) -> DuplicateAssessment:
    """Assess only exact normalized identity signals; never merge products."""

    normalized_a = normalize_part_number(mpn_a).normalized_value
    normalized_b = normalize_part_number(mpn_b).normalized_value
    if not normalized_a or not normalized_b:
        return DuplicateAssessment(DuplicateStatus.INSUFFICIENT_DATA, (), "missing_part_number")
    if normalized_a != normalized_b:
        return DuplicateAssessment(
            DuplicateStatus.DISTINCT, ("mpn_mismatch",), "normalized_part_numbers_differ"
        )
    manufacturer_a_key = normalize_part_number(manufacturer_a).normalized_value
    manufacturer_b_key = normalize_part_number(manufacturer_b).normalized_value
    if manufacturer_a_key and manufacturer_b_key:
        if manufacturer_a_key == manufacturer_b_key:
            return DuplicateAssessment(
                DuplicateStatus.EXACT_DUPLICATE,
                ("manufacturer", "mpn"),
                "same_normalized_manufacturer_and_mpn",
            )
        return DuplicateAssessment(
            DuplicateStatus.POSSIBLE_DUPLICATE, ("mpn",), "same_mpn_different_manufacturer"
        )
    return DuplicateAssessment(
        DuplicateStatus.POSSIBLE_DUPLICATE, ("mpn",), "same_mpn_missing_manufacturer"
    )
