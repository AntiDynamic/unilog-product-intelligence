"""Regression tests for MPN-prefix brand resolution.

These tests cover the two official ground-truth products that previously
failed with DOMAIN_UNRESOLVED because their Part_Manuf is a distributor
(APPDE) and their Part_Desc contains no explicit brand keyword.
"""

from __future__ import annotations

from unilog_product_intelligence.application.brand_resolver import (
    BrandManufacturerResolver,
    _match_mpn_prefix,
)
from unilog_product_intelligence.retrieval.core import DomainResolver

# ---- _match_mpn_prefix unit tests ------------------------------------------


class TestMatchMpnPrefix:
    def test_pdsh_maps_to_frigidaire(self) -> None:
        result = _match_mpn_prefix("PDSH4816AF")
        assert result is not None
        mfg_key, brand = result
        assert mfg_key == "frigidaire"
        assert brand == "Frigidaire"

    def test_wdts_maps_to_whirlpool(self) -> None:
        result = _match_mpn_prefix("WDTS7024RZ")
        assert result is not None
        mfg_key, brand = result
        assert mfg_key == "whirlpool"
        assert brand == "Whirlpool"

    def test_unknown_prefix_returns_none(self) -> None:
        assert _match_mpn_prefix("XYZ999ABC") is None

    def test_empty_mpn_returns_none(self) -> None:
        assert _match_mpn_prefix("") is None

    def test_case_insensitive(self) -> None:
        assert _match_mpn_prefix("pdsh4816af") is not None
        assert _match_mpn_prefix("wdts7024rz") is not None

    def test_longer_prefix_wins_over_shorter(self) -> None:
        result = _match_mpn_prefix("WDTS7024RZ")
        assert result is not None
        assert result[0] == "whirlpool"

    def test_kdte_maps_to_kitchenaid(self) -> None:
        result = _match_mpn_prefix("KDTE204KBS")
        assert result is not None
        assert result[0] == "kitchenaid"

    def test_mdb_maps_to_maytag(self) -> None:
        result = _match_mpn_prefix("MDB8989SHZ")
        assert result is not None
        assert result[0] == "maytag"


# ---- BrandManufacturerResolver.resolve integration tests --------------------

APPDE = "Appliance Dealers Cooperative (APPDE)"
PDSH_DESC = "PDSH4816AF Dishwasher SS - Display Only"
WDTS_DESC = "WDTS7024RZ Dishwasher SS - Display Only"


class TestBrandManufacturerResolverMpnFallback:
    def setup_method(self) -> None:
        self.resolver = BrandManufacturerResolver()

    def test_pdsh4816af_resolves_frigidaire(self) -> None:
        result = self.resolver.resolve(APPDE, PDSH_DESC, mpn="PDSH4816AF")
        assert result.manufacturer == "frigidaire"
        assert result.brand == "Frigidaire"
        assert result.resolution_method == "mpn_prefix"
        assert result.is_distributor is True

    def test_wdts7024rz_resolves_whirlpool(self) -> None:
        result = self.resolver.resolve(APPDE, WDTS_DESC, mpn="WDTS7024RZ")
        assert result.manufacturer == "whirlpool"
        assert result.brand == "Whirlpool"
        assert result.resolution_method == "mpn_prefix"
        assert result.is_distributor is True

    def test_desc_brand_token_still_wins_over_mpn_prefix(self) -> None:
        result = self.resolver.resolve(
            APPDE,
            "Frigidaire PDSH4816AF Built-In Dishwasher",
            mpn="PDSH4816AF",
        )
        assert result.resolution_method == "desc_brand_token"
        assert result.manufacturer == "frigidaire"

    def test_without_mpn_still_unresolved_for_appde(self) -> None:
        result = self.resolver.resolve(APPDE, PDSH_DESC)
        assert result.resolution_method == "unresolved"
        assert result.is_distributor is True

    def test_backwards_compat_no_mpn_kwarg(self) -> None:
        result = self.resolver.resolve("Jam Industrial Supply LLC (JAMIN)", "3M Stikit Film")
        assert result.manufacturer == "3m"
        assert result.resolution_method == "distributor_map"


# ---- DomainResolver catalog tests ------------------------------------------


class TestDomainResolverApplianceCatalog:
    def setup_method(self) -> None:
        self.dr = DomainResolver()

    def _domains(self, mfg_key: str) -> tuple[str, ...]:
        from unilog_product_intelligence.retrieval.core import _manufacturer_key
        return self.dr._known_manufacturer_domains.get(_manufacturer_key(mfg_key), ())

    def test_frigidaire_in_catalog(self) -> None:
        assert "frigidaire.com" in self._domains("frigidaire")

    def test_whirlpool_in_catalog(self) -> None:
        assert "whirlpool.com" in self._domains("whirlpool")

    def test_rheem_in_catalog(self) -> None:
        assert "rheem.com" in self._domains("rheem")

    def test_maytag_in_catalog(self) -> None:
        assert "maytag.com" in self._domains("maytag")

    def test_kitchenaid_in_catalog(self) -> None:
        assert "kitchenaid.com" in self._domains("kitchenaid")

    def test_ge_appliances_in_catalog(self) -> None:
        assert "geappliances.com" in self._domains("ge appliances")

    def test_samsung_in_catalog(self) -> None:
        assert "samsung.com" in self._domains("samsung")

    def test_lg_in_catalog(self) -> None:
        assert "lg.com" in self._domains("lg")

    def test_domain_resolver_resolve_frigidaire(self) -> None:
        from unilog_product_intelligence.retrieval.core import SourceDecision
        candidates = self.dr.resolve("frigidaire", "frigidaire")
        assert len(candidates) > 0
        assert candidates[0].domain == "frigidaire.com"
        assert candidates[0].status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE

    def test_domain_resolver_resolve_whirlpool(self) -> None:
        from unilog_product_intelligence.retrieval.core import SourceDecision
        candidates = self.dr.resolve("whirlpool", "whirlpool")
        assert len(candidates) > 0
        assert candidates[0].domain == "whirlpool.com"
        assert candidates[0].status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
