"""Unit tests for MpnNormalizer."""

from __future__ import annotations

from unilog_product_intelligence.retrieval.mpn_normalizer import (
    MpnHypothesisType,
    MpnNormalizer,
)


def test_mpn_normalizer_3m_distributor_prefix_with_manufacturer_hint() -> None:
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("3MABR-7100075678", manufacturer_hint="3M")
    values = [h.value for h in hypotheses]
    assert "3MABR-7100075678" in values
    assert "7100075678" in values

    h_raw = next(h for h in hypotheses if h.value == "3MABR-7100075678")
    assert h_raw.hypothesis_type == MpnHypothesisType.RAW
    assert h_raw.is_lossless is True
    assert h_raw.identity_eligible is True

    h_stripped = next(h for h in hypotheses if h.value == "7100075678")
    assert h_stripped.hypothesis_type in {
        MpnHypothesisType.VERIFIED_MANUFACTURER_TRANSFORM,
        MpnHypothesisType.STRIPPED_DISTRIBUTOR_PREFIX,
        MpnHypothesisType.NUMERIC_CORE_ID,
    }
    assert h_stripped.identity_eligible is True


def test_mpn_normalizer_generic_prefix_without_hint_is_exploratory_only() -> None:
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("AB-123456", manufacturer_hint=None)
    values = [h.value for h in hypotheses]
    assert "AB-123456" in values
    assert "AB123456" in values
    assert "123456" in values

    h_raw = next(h for h in hypotheses if h.value == "AB-123456")
    assert h_raw.hypothesis_type == MpnHypothesisType.RAW
    assert h_raw.identity_eligible is True

    h_lossless = next(h for h in hypotheses if h.value == "AB123456")
    assert h_lossless.hypothesis_type == MpnHypothesisType.LOSSLESS_NORMALIZED
    assert h_lossless.is_lossless is True
    assert h_lossless.identity_eligible is True

    h_exploratory = next(h for h in hypotheses if h.value == "123456")
    assert h_exploratory.hypothesis_type == MpnHypothesisType.EXPLORATORY_PREFIX_STRIP
    assert h_exploratory.is_lossless is False
    assert h_exploratory.identity_eligible is False


def test_mpn_normalizer_milwaukee_hyphenated() -> None:
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("49-94-0013")
    values = [h.value for h in hypotheses]
    assert "49-94-0013" in values
    assert "49940013" in values

    h_raw = next(h for h in hypotheses if h.value == "49-94-0013")
    assert h_raw.is_lossless is True
    assert h_raw.identity_eligible is True

    h_compact = next(h for h in hypotheses if h.value == "49940013")
    assert h_compact.is_lossless is True
    assert h_compact.identity_eligible is True


def test_mpn_normalizer_diablo_clean_mpn() -> None:
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("DCB518ASTS06G")
    assert len(hypotheses) == 1
    assert hypotheses[0].value == "DCB518ASTS06G"
    assert hypotheses[0].hypothesis_type == MpnHypothesisType.RAW
    assert hypotheses[0].is_lossless is True
    assert hypotheses[0].identity_eligible is True


def test_mpn_normalizer_mirka_part_number() -> None:
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("5B-332-080")
    values = [h.value for h in hypotheses]
    assert "5B-332-080" in values
    assert "5B332080" in values
