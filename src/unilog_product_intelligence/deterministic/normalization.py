"""Safe reversible text and identifier normalization; no semantic expansion."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from unilog_product_intelligence.data.normalize import normalize_value

_SPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w]+", flags=re.UNICODE)


@dataclass(frozen=True)
class NormalizationResult:
    raw_value: Any
    normalized_value: str | None
    reason: str | None


def normalize_text(
    value: Any, *, casefold: bool = False, canonicalize: bool = False
) -> NormalizationResult:
    """Normalize Unicode/whitespace safely and preserve the original value."""

    base = normalize_value(value)
    if base.normalized_value is None:
        return NormalizationResult(base.raw_value, None, base.reason)
    normalized = _SPACE.sub(" ", unicodedata.normalize("NFKC", base.normalized_value)).strip()
    if canonicalize:
        normalized = _PUNCTUATION.sub("", normalized)
    if casefold:
        normalized = normalized.casefold()
    reason = base.reason or ("normalized_text" if normalized != base.raw_value else None)
    return NormalizationResult(base.raw_value, normalized, reason)


def normalize_part_number(value: Any) -> NormalizationResult:
    """Apply only reversible whitespace, Unicode, and case normalization to a part number."""

    result = normalize_text(value)
    if result.normalized_value is None:
        return result
    normalized = result.normalized_value.upper()
    reason = result.reason or ("uppercase" if normalized != result.raw_value else None)
    return NormalizationResult(result.raw_value, normalized, reason)
