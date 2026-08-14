"""Traceable reference registries and controlled resolution results."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum

from .normalization import normalize_text


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    REFERENCE_DATA_UNAVAILABLE = "reference_data_unavailable"


class MatchType(StrEnum):
    EXACT = "exact"
    NORMALIZED_EXACT = "normalized_exact"
    CANONICALIZED = "canonicalized"
    FUZZY_CANDIDATE = "fuzzy_candidate"
    NONE = "none"


@dataclass(frozen=True)
class ReferenceRecord:
    record_id: str
    canonical_name: str
    code: str | None = None
    manufacturer_id: str | None = None
    aliases: tuple[str, ...] = ()
    source_id: str | None = None
    raw_reference: str | None = None


@dataclass(frozen=True)
class ResolutionCandidate:
    record: ReferenceRecord
    score: float
    match_type: MatchType


@dataclass(frozen=True)
class ResolutionResult:
    raw_value: str | None
    status: ResolutionStatus
    match_type: MatchType = MatchType.NONE
    canonical_record: ReferenceRecord | None = None
    score: float | None = None
    candidates: tuple[ResolutionCandidate, ...] = ()
    reason: str | None = None
    reference_source: str | None = None


@dataclass(frozen=True)
class ResolutionPolicy:
    fuzzy_threshold: float = 0.88
    max_fuzzy_candidates: int = 5


@dataclass
class ReferenceRegistry:
    """Indexed generic registry. Empty/unloaded registries report unavailability explicitly."""

    records: tuple[ReferenceRecord, ...] = ()
    available: bool = False
    source_id: str | None = None
    policy: ResolutionPolicy = field(default_factory=ResolutionPolicy)

    def __post_init__(self) -> None:
        self._by_code = {record.code.casefold(): record for record in self.records if record.code}
        self._exact: dict[str, list[ReferenceRecord]] = {}
        self._normalized: dict[str, list[ReferenceRecord]] = {}
        self._canonical: dict[str, list[ReferenceRecord]] = {}
        for record in self.records:
            for name in (record.canonical_name, *record.aliases):
                self._exact.setdefault(name, []).append(record)
                self._normalized.setdefault(_key(name), []).append(record)
                self._canonical.setdefault(_canonical_key(name), []).append(record)

    def get_by_code(self, code: str) -> ReferenceRecord | None:
        return self._by_code.get(code.casefold()) if self.available else None

    def get_by_name(self, name: str) -> ResolutionResult:
        return self.resolve(name)

    def resolve(self, raw_value: str | None) -> ResolutionResult:
        if not self.available:
            return ResolutionResult(
                raw_value,
                ResolutionStatus.REFERENCE_DATA_UNAVAILABLE,
                reason="registry_not_loaded",
                reference_source=self.source_id,
            )
        if raw_value is None or normalize_text(raw_value).normalized_value is None:
            return ResolutionResult(
                raw_value,
                ResolutionStatus.UNRESOLVED,
                reason="missing_or_placeholder",
                reference_source=self.source_id,
            )
        return self._resolve_candidates(raw_value, self.records)

    def _resolve_candidates(
        self, raw_value: str, candidates: Iterable[ReferenceRecord]
    ) -> ResolutionResult:
        candidate_tuple = tuple(candidates)
        exact = tuple(
            record
            for record in candidate_tuple
            if raw_value in {record.canonical_name, *record.aliases}
        )
        if exact:
            return _resolved_or_ambiguous(raw_value, exact, MatchType.EXACT, 1.0, self.source_id)
        normalized_key = _key(raw_value)
        normalized = tuple(
            record
            for record in candidate_tuple
            if normalized_key
            in {_key(record.canonical_name), *(_key(alias) for alias in record.aliases)}
        )
        if normalized:
            return _resolved_or_ambiguous(
                raw_value, normalized, MatchType.NORMALIZED_EXACT, 1.0, self.source_id
            )
        canonical_key = _canonical_key(raw_value)
        canonical = tuple(
            record
            for record in candidate_tuple
            if canonical_key
            in {
                _canonical_key(record.canonical_name),
                *(_canonical_key(alias) for alias in record.aliases),
            }
        )
        if canonical:
            return _resolved_or_ambiguous(
                raw_value, canonical, MatchType.CANONICALIZED, 1.0, self.source_id
            )
        ranked = sorted(
            (
                ResolutionCandidate(
                    record,
                    SequenceMatcher(
                        None, canonical_key, _canonical_key(record.canonical_name)
                    ).ratio(),
                    MatchType.FUZZY_CANDIDATE,
                )
                for record in candidate_tuple
            ),
            key=lambda candidate: candidate.score,
            reverse=True,
        )
        fuzzy: tuple[ResolutionCandidate, ...] = tuple(
            candidate for candidate in ranked if candidate.score >= self.policy.fuzzy_threshold
        )[: self.policy.max_fuzzy_candidates]
        if fuzzy:
            return ResolutionResult(
                raw_value,
                ResolutionStatus.AMBIGUOUS,
                MatchType.FUZZY_CANDIDATE,
                candidates=fuzzy,
                reason="fuzzy_candidates_require_review",
                reference_source=self.source_id,
            )
        return ResolutionResult(
            raw_value,
            ResolutionStatus.UNRESOLVED,
            reason="no_match",
            reference_source=self.source_id,
        )


class ManufacturerRegistry(ReferenceRegistry):
    """Reference registry for approved manufacturer records."""


class BrandRegistry(ReferenceRegistry):
    """Reference registry for approved brands with optional manufacturer context."""

    def get_for_manufacturer(self, manufacturer_id: str) -> tuple[ReferenceRecord, ...]:
        return tuple(record for record in self.records if record.manufacturer_id == manufacturer_id)

    def resolve_for_manufacturer(
        self, raw_value: str | None, manufacturer_id: str | None
    ) -> ResolutionResult:
        if not self.available:
            return ResolutionResult(
                raw_value,
                ResolutionStatus.REFERENCE_DATA_UNAVAILABLE,
                reason="registry_not_loaded",
                reference_source=self.source_id,
            )
        candidates = self.get_for_manufacturer(manufacturer_id) if manufacturer_id else self.records
        if manufacturer_id and not candidates:
            return ResolutionResult(
                raw_value,
                ResolutionStatus.UNRESOLVED,
                reason="no_brands_for_manufacturer",
                reference_source=self.source_id,
            )
        if raw_value is None or normalize_text(raw_value).normalized_value is None:
            return ResolutionResult(
                raw_value,
                ResolutionStatus.UNRESOLVED,
                reason="missing_or_placeholder",
                reference_source=self.source_id,
            )
        return self._resolve_candidates(raw_value, candidates)


class TaxonomyRegistry(ReferenceRegistry):
    """Future taxonomy registry; unavailable until approved taxonomy files are loaded."""


class LOVRegistry(ReferenceRegistry):
    """Future category-scoped LOV registry; no values are bundled here."""


class UOMRegistry(ReferenceRegistry):
    """Future approved-UOM registry; no Unilog representations are assumed."""


class FractionRegistry(ReferenceRegistry):
    """Future official Decimal_Fraction lookup registry."""


class RuleRegistry(ReferenceRegistry):
    """Future official content/rule registry."""


def _key(value: str) -> str:
    return normalize_text(value, casefold=True).normalized_value or ""


def _canonical_key(value: str) -> str:
    return normalize_text(value, casefold=True, canonicalize=True).normalized_value or ""


def _resolved_or_ambiguous(
    raw: str,
    records: tuple[ReferenceRecord, ...],
    match_type: MatchType,
    score: float,
    source_id: str | None,
) -> ResolutionResult:
    if len(records) == 1:
        return ResolutionResult(
            raw,
            ResolutionStatus.RESOLVED,
            match_type,
            records[0],
            score,
            reference_source=source_id,
        )
    candidates = tuple(ResolutionCandidate(record, score, match_type) for record in records)
    return ResolutionResult(
        raw,
        ResolutionStatus.AMBIGUOUS,
        match_type,
        candidates=candidates,
        reason="multiple_matching_records",
        reference_source=source_id,
    )
