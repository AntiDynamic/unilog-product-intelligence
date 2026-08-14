from decimal import Decimal

from unilog_product_intelligence.deterministic.duplicates import (
    DuplicateStatus,
    assess_duplicate,
)
from unilog_product_intelligence.deterministic.fractions import (
    FractionSource,
    decimal_to_fraction,
)
from unilog_product_intelligence.deterministic.metrics import DeterministicMetrics
from unilog_product_intelligence.deterministic.normalization import normalize_part_number
from unilog_product_intelligence.deterministic.registry import (
    BrandRegistry,
    ManufacturerRegistry,
    MatchType,
    ReferenceRecord,
    ResolutionStatus,
)


def test_part_number_normalization_is_reversible_and_conservative() -> None:
    result = normalize_part_number("  sample-part  ")

    assert result.raw_value == "  sample-part  "
    assert result.normalized_value == "SAMPLE-PART"


def test_unloaded_registry_does_not_claim_a_resolution() -> None:
    result = ManufacturerRegistry().resolve("Synthetic Manufacturer")

    assert result.status == ResolutionStatus.REFERENCE_DATA_UNAVAILABLE


def test_registry_resolves_only_exact_normalized_records() -> None:
    registry = ManufacturerRegistry(
        records=(ReferenceRecord("m-1", "Synthetic Manufacturer"),),
        available=True,
        source_id="synthetic-test-registry",
    )

    result = registry.resolve(" synthetic manufacturer ")

    assert result.status == ResolutionStatus.RESOLVED
    assert result.match_type == MatchType.NORMALIZED_EXACT
    assert result.canonical_record is not None
    assert result.canonical_record.record_id == "m-1"


def test_fuzzy_matches_are_review_candidates_not_resolutions() -> None:
    registry = ManufacturerRegistry(
        records=(ReferenceRecord("m-1", "Synthetic Manufacturer"),),
        available=True,
        source_id="synthetic-test-registry",
    )

    result = registry.resolve("Synthetic Manufactur")

    assert result.status == ResolutionStatus.AMBIGUOUS
    assert result.match_type == MatchType.FUZZY_CANDIDATE
    assert result.canonical_record is None


def test_brand_resolution_respects_manufacturer_context() -> None:
    registry = BrandRegistry(
        records=(
            ReferenceRecord("b-1", "Synthetic Brand", manufacturer_id="m-1"),
            ReferenceRecord("b-2", "Synthetic Brand", manufacturer_id="m-2"),
        ),
        available=True,
    )

    result = registry.resolve_for_manufacturer("Synthetic Brand", "m-1")

    assert result.status == ResolutionStatus.RESOLVED
    assert result.canonical_record is not None
    assert result.canonical_record.record_id == "b-1"


def test_fraction_conversion_is_labelled_calculated_not_official_lookup() -> None:
    result = decimal_to_fraction(Decimal("0.5"))

    assert result.normalized_value == "1/2"
    assert result.source == FractionSource.CALCULATED


def test_duplicate_assessment_never_merges_records() -> None:
    assessment = assess_duplicate(
        "Synthetic Maker", "sample-part", "synthetic maker", "SAMPLE-PART"
    )

    assert assessment.status == DuplicateStatus.EXACT_DUPLICATE
    assert assessment.reason == "same_normalized_manufacturer_and_mpn"


def test_metrics_count_explicit_resolution_outcomes() -> None:
    metrics = DeterministicMetrics()
    metrics.record_resolution("manufacturer", ResolutionStatus.UNRESOLVED)

    assert metrics.as_dict() == {"manufacturer.unresolved": 1}
