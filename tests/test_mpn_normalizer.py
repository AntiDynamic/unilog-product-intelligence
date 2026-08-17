"""Unit tests for MpnNormalizer."""

from __future__ import annotations

from unilog_product_intelligence.retrieval.mpn_normalizer import (
    MpnHypothesisType,
    MpnNormalizer,
)


def test_mpn_normalizer_3m_distributor_prefix() -> None:
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("3MABR-7100075678")
    values = [h.value for h in hypotheses]
    assert "3MABR-7100075678" in values
    assert "7100075678" in values

    h_stripped = next(h for h in hypotheses if h.value == "7100075678")
    assert h_stripped.hypothesis_type in {
        MpnHypothesisType.STRIPPED_DISTRIBUTOR_PREFIX,
        MpnHypothesisType.NUMERIC_CORE_ID,
    }


def test_mpn_normalizer_milwaukee_hyphenated() -> None:
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("49-94-0013")
    values = [h.value for h in hypotheses]
    assert "49-94-0013" in values
    assert "49940013" in values


def test_mpn_normalizer_diablo_clean_mpn() -> None:
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("DCB518ASTS06G")
    assert len(hypotheses) == 1
    assert hypotheses[0].value == "DCB518ASTS06G"
    assert hypotheses[0].hypothesis_type == MpnHypothesisType.RAW


def test_mpn_normalizer_mirka_part_number() -> None:
    normalizer = MpnNormalizer()
    hypotheses = normalizer.normalize("5B-332-080")
    values = [h.value for h in hypotheses]
    assert "5B-332-080" in values
    assert "5B332080" in values
