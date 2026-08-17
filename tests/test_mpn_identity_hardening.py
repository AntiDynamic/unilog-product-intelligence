"""Tests for hardened MPN normalization, ranking, and exact product identity verification.

Covers:
  - Whole-token boundary matching
  - Separation of search hypotheses from verified identity
  - Seven explicit acceptance/rejection cases
  - Positive regression products (Diablo, Milwaukee, Freud/Diablo)
  - Negative false-positive boundary tests (Tests A-E)
"""

from __future__ import annotations

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.models import Source, SourceAuthority, SourceType
from unilog_product_intelligence.domain.truth import ProductTruth
from unilog_product_intelligence.retrieval.source_discovery import (
    MpnMatchClassification,
    ProductIdentityMatcher,
)


def _make_product(
    mpn: str,
    manufacturer: str = "Acme Corp",
    brand: str = "Acme",
    desc: str = "Industrial standard product",
) -> ProductTruth:
    raw: dict[str, object] = {
        "Mfg_Part_Num": mpn,
        "Part_Desc": desc,
        "Part_Manuf": manufacturer,
    }
    if brand:
        raw["Unilog_Brand"] = brand
    return ProductTruthService().create_from_raw_input(
        "test-prod-1",
        raw,
        Source(
            source_id="input",
            source_type=SourceType.SUPPLIED_INPUT,
            authority=SourceAuthority.HIGH,
        ),
    )


def _make_document(
    title: str = "",
    body: str = "",
    metadata: dict[str, object] | None = None,
) -> object:
    return type(
        "Document",
        (),
        {
            "title": title,
            "chunks": [type("Chunk", (), {"text": body})()] if body else [],
            "structured_metadata": metadata or {},
        },
    )()


# ==============================================================================
# Part 8 & 11: Whole-Token Boundary Tests and Negative Cases (Tests A-E)
# ==============================================================================


def test_negative_case_a_substring_mpn_rejected() -> None:
    """TEST A: Input 'ABC123' must NOT match page with 'ABC1234'."""
    product = _make_product(mpn="ABC123", manufacturer="Acme Corp")
    doc = _make_document(
        title="Acme ABC1234 Part",
        body="Acme Corp heavy duty ABC1234 industrial component",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.raw_mpn_match is False
    assert match.normalized_mpn_match is False
    assert match.matched_mpn is False
    assert match.mpn_match_type == MpnMatchClassification.NO_MATCH
    assert match.identity_score < 0.6
    assert match.classification in {"WEAK_MATCH", "MISMATCH"}
    assert match.rejection_reason == "MPN_NOT_FOUND"


def test_negative_case_b_family_name_without_exact_mpn_rejected() -> None:
    """TEST B: Input 'ABC123' must NOT match page containing only 'ABC123-family'."""
    product = _make_product(mpn="ABC123", manufacturer="Acme Corp")
    doc = _make_document(
        title="Acme ABC123-family Product Line",
        body="Overview of the Acme Corp ABC123-family product series and catalog.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.raw_mpn_match is False
    assert match.matched_mpn is False
    assert match.mpn_match_type == MpnMatchClassification.NO_MATCH
    assert match.identity_score < 0.6
    assert match.rejection_reason == "MPN_NOT_FOUND"


def test_negative_case_c_generic_prefix_strip_without_mfg_rule_is_exploratory_only() -> None:
    """TEST C: Input 'AB-123456' on page with '123456' (no mfg rule) is EXPLORATORY and REJECTED."""
    product = _make_product(mpn="AB-123456", manufacturer="Acme Corp", brand="Acme")
    doc = _make_document(
        title="Acme 123456 Item",
        body="Acme Corp product with number 123456 in stock.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.raw_mpn_match is False
    assert match.normalized_mpn_match is False
    assert match.transformed_mpn_match is True
    assert match.mpn_match_type == MpnMatchClassification.EXPLORATORY_ONLY
    assert match.matched_mpn is False  # Cannot establish identity on exploratory alone
    assert match.identity_score < 0.6
    assert match.classification == "WEAK_MATCH"
    assert match.rejection_reason == "EXPLORATORY_MPN_UNVERIFIED"


def test_case_d_verified_manufacturer_profile_transformation_can_be_accepted() -> None:
    """TEST D: Transformed MPN with verified manufacturer rule + brand + desc is ACCEPTED."""
    product = _make_product(
        mpn="3MABR-7100075678",
        manufacturer="3M",
        brand="3M",
        desc="Cloth Belt 777F ceramic abrasive",
    )
    doc = _make_document(
        title="3M Cloth Belt 777F Item 7100075678",
        body="3M ceramic abrasive cloth belt item 7100075678 high performance grinding.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.raw_mpn_match is False
    assert match.transformed_mpn_match is True
    assert match.mpn_match_type == MpnMatchClassification.VERIFIED_TRANSFORMED
    assert match.matched_mpn is True
    assert match.matched_manufacturer is True
    assert match.matched_brand is True
    assert match.identity_score >= 0.6
    assert match.classification == "STRONG_MATCH"
    assert match.rejection_reason is None


def test_case_e_known_3m_distributor_prefix_matches_as_verified_transform() -> None:
    """TEST E: Input '3MABR-7100075678' on page with '7100075678' is VERIFIED_TRANSFORMED."""
    product = _make_product(
        mpn="3MABR-7100075678",
        manufacturer="Jam Industrial Supply LLC (3M)",
        brand="3M",
        desc="3M 777F Abrasive Belt",
    )
    doc = _make_document(
        title="3M 777F Abrasive Belt 7100075678",
        body="3M 7100075678 industrial abrasive belt.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.raw_mpn_match is False
    assert match.transformed_mpn_match is True
    assert match.mpn_match_type == MpnMatchClassification.VERIFIED_TRANSFORMED
    assert match.matched_mpn is True
    assert match.identity_score >= 0.6


def test_whole_token_embedded_numeric_substring_rejected() -> None:
    """Input '123456' must NOT match page with 'ABC123456XYZ'."""
    product = _make_product(mpn="123456", manufacturer="Acme Corp")
    doc = _make_document(
        title="Acme ABC123456XYZ Model",
        body="Acme Corp product ABC123456XYZ specifications and overview.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.matched_mpn is False
    assert match.identity_score < 0.6
    assert match.rejection_reason == "MPN_NOT_FOUND"


# ==============================================================================
# Part 7: Cases 1 to 7 Safe Acceptance Decision Matrix
# ==============================================================================


def test_case_1_raw_exact_mpn_with_manufacturer_accepted() -> None:
    """CASE 1: RAW_EXACT + manufacturer match -> ACCEPT."""
    product = _make_product(mpn="49-94-0013", manufacturer="Milwaukee Tool", brand="Milwaukee")
    doc = _make_document(
        title="Milwaukee 49-94-0013 Cut-Off Wheel",
        body="Milwaukee Tool 49-94-0013 3 inch metal cut off wheel.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.raw_mpn_match is True
    assert match.mpn_match_type == MpnMatchClassification.RAW_EXACT
    assert match.matched_mpn is True
    assert match.identity_score >= 0.8
    assert match.classification == "EXACT_MATCH"
    assert match.rejection_reason is None


def test_case_2_lossless_normalized_equivalent_accepted() -> None:
    """CASE 2: LOSSLESS_NORMALIZED (separator/compact variant) + manufacturer match -> ACCEPT."""
    product = _make_product(mpn="49-94-0013", manufacturer="Milwaukee Tool", brand="Milwaukee")
    # Page text uses compact 49940013
    doc = _make_document(
        title="Milwaukee Cut-Off Wheel Model 49940013",
        body="Milwaukee Tool product 49940013 abrasive blade.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.raw_mpn_match is False
    assert match.normalized_mpn_match is True
    assert match.mpn_match_type == MpnMatchClassification.LOSSLESS_NORMALIZED
    assert match.matched_mpn is True
    assert match.identity_score >= 0.6
    assert match.classification in {"STRONG_MATCH", "EXACT_MATCH"}
    assert match.rejection_reason is None


def test_case_3_verified_transformed_without_manufacturer_match_rejected() -> None:
    """CASE 3 Negative: VERIFIED_TRANSFORMED without manufacturer match -> REJECT."""
    product = _make_product(
        mpn="3MABR-7100075678",
        manufacturer="3M",
        brand="3M",
        desc="Cloth Belt",
    )
    # Page has transformed MPN 7100075678 but wrong manufacturer "Bosch"
    doc = _make_document(
        title="Bosch Item 7100075678",
        body="Bosch power tool part 7100075678 accessory.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.matched_mpn is False
    assert match.identity_score < 0.6
    assert match.rejection_reason == "TRANSFORMED_MPN_REQUIRES_MANUFACTURER_MATCH"


def test_case_6_brand_only_with_similar_desc_rejected() -> None:
    """CASE 6: Brand only + similar description (no MPN match) -> DO NOT ACCEPT."""
    product = _make_product(
        mpn="DCB518ASTS06G",
        manufacturer="Diablo",
        brand="Diablo",
        desc="Sanding belt 80 grit ceramic",
    )
    doc = _make_document(
        title="Diablo Sanding Belts Catalog",
        body="Diablo ceramic sanding belt 80 grit abrasive belts for shop sanders.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.matched_mpn is False
    assert match.raw_mpn_match is False
    assert match.identity_score < 0.6
    assert match.rejection_reason == "MPN_NOT_FOUND"


def test_case_7_manufacturer_only_with_similar_title_rejected() -> None:
    """CASE 7: Manufacturer only + similar title (no MPN match) -> DO NOT ACCEPT."""
    product = _make_product(
        mpn="49-94-0013",
        manufacturer="Milwaukee Tool",
        brand="Milwaukee",
        desc="Cut-off wheel",
    )
    doc = _make_document(
        title="Milwaukee Tool Metal Cut-Off Wheels",
        body="Milwaukee Tool heavy duty cut-off wheels for grinders.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.matched_mpn is False
    assert match.identity_score < 0.6
    assert match.rejection_reason == "MPN_NOT_FOUND"


# ==============================================================================
# Part 10: Regression Tests on Currently Successful Products
# ==============================================================================


def test_positive_regression_diablo_clean_mpn() -> None:
    """Product 1: Diablo DCB518ASTS06G."""
    product = _make_product(
        mpn="DCB518ASTS06G",
        manufacturer="Freud Inc (2435)",
        brand="Diablo",
        desc="Diablo 5 x 18 in 60 Grit Sanding Belt",
    )
    doc = _make_document(
        title="Diablo DCB518ASTS06G 5 x 18 In. 60-Grit Sanding Belt",
        body="Freud Inc Diablo DCB518ASTS06G 60 grit sanding belt for portable belt sanders.",
        metadata={"mpn": "DCB518ASTS06G", "brand": "Diablo"},
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.raw_mpn_match is True
    assert match.matched_mpn is True
    assert match.mpn_match_type == MpnMatchClassification.RAW_EXACT
    assert match.identity_score >= 0.8
    assert match.classification == "EXACT_MATCH"


def test_positive_regression_milwaukee_hyphenated_mpn() -> None:
    """Product 2: Milwaukee 49-94-0013."""
    product = _make_product(
        mpn="49-94-0013",
        manufacturer="Milwaukee Tool",
        brand="Milwaukee",
        desc="3 in. Metal Cut Off Wheel (3 PK)",
    )
    doc = _make_document(
        title="3 in. Metal Cut Off Wheel (3 PK) | Milwaukee Tool",
        body="Model 49-94-0013 Milwaukee Tool 3 in metal cut off wheel accessory pack.",
        metadata={"mpn": "49-94-0013", "manufacturer": "Milwaukee Tool"},
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.raw_mpn_match is True
    assert match.matched_mpn is True
    assert match.mpn_match_type == MpnMatchClassification.RAW_EXACT
    assert match.identity_score >= 0.8
    assert match.classification == "EXACT_MATCH"


def test_positive_regression_freud_diablo_dbd() -> None:
    """Product 3: Freud/Diablo DBD090094101F."""
    product = _make_product(
        mpn="DBD090094101F",
        manufacturer="Freud Inc (2435)",
        brand="Diablo",
        desc="Demo Demon Carbide Teeth Reciprocating Blade",
    )
    doc = _make_document(
        title="Diablo Demo Demon Reciprocating Saw Blade DBD090094101F",
        body="Freud Diablo DBD090094101F Demo Demon carbide reciprocating blade for nails in wood.",
    )
    matcher = ProductIdentityMatcher()
    match = matcher.match(product, doc)

    assert match.raw_mpn_match is True
    assert match.matched_mpn is True
    assert match.mpn_match_type == MpnMatchClassification.RAW_EXACT
    assert match.identity_score >= 0.8
    assert match.classification == "EXACT_MATCH"
