"""Deterministic preprocessing, resolution, validation, and diagnostics."""

from .duplicates import DuplicateAssessment, DuplicateStatus, assess_duplicate
from .fractions import FractionConversion, FractionSource, decimal_to_fraction, fraction_to_decimal
from .normalization import normalize_part_number, normalize_text
from .registry import BrandRegistry, ManufacturerRegistry, ReferenceRecord, ResolutionResult

__all__ = [
    "BrandRegistry",
    "DuplicateAssessment",
    "DuplicateStatus",
    "FractionConversion",
    "FractionSource",
    "ManufacturerRegistry",
    "ReferenceRecord",
    "ResolutionResult",
    "assess_duplicate",
    "decimal_to_fraction",
    "fraction_to_decimal",
    "normalize_part_number",
    "normalize_text",
]
