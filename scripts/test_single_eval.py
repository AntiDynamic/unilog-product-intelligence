"""Test single product execution for fast diagnostics."""

from __future__ import annotations

from pathlib import Path

from unilog_product_intelligence.application.evaluation import (
    DatasetSampler,
    DeterministicEvaluationProvider,
)
from unilog_product_intelligence.application.phase65 import _extract_brand, _identity_value
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.truth import Source, SourceAuthority, SourceType
from unilog_product_intelligence.retrieval.agents import ManufacturerDiscoveryAgent
from unilog_product_intelligence.retrieval.core import (
    DomainResolver,
    ManufacturerProfile,
    SourceFetcher,
)
from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService


def main() -> None:
    root_dir = Path(__file__).resolve().parent.parent
    input_csv = root_dir / "Unihack_ Sample Dataset - Input.csv"

    sampler = DatasetSampler(input_csv)
    rec = sampler.records[0]

    truth_service = ProductTruthService()
    raw_dict = {
        "Mfg_Part_Num": rec.mpn,
        "Part_Desc": rec.description,
        "E1_Brand": rec.e1_brand,
        "Unilog_Brand": rec.unilog_brand,
        "DIB_Brand": rec.dib_brand,
        "Part_Manuf": rec.manufacturer,
    }
    source = Source(
        source_id="test",
        source_type=SourceType.SUPPLIED_INPUT,
        authority=SourceAuthority.HIGH,
    )
    prod = truth_service.create_from_raw_input("prod-1", raw_dict, source)

    mfg_name = _identity_value(prod, "manufacturer") or ""
    brand = _extract_brand(prod)

    resolver = DomainResolver()
    disc_agent = ManufacturerDiscoveryAgent(
        provider=DeterministicEvaluationProvider(), resolver=resolver
    )
    disc_res = disc_agent.discover(
        manufacturer_id=mfg_name,
        manufacturer_name=mfg_name,
        mpn="DCB518ASTS06G",
        description=str(prod.raw_value("Part_Desc") or ""),
        brand=brand,
    )

    fetcher = SourceFetcher()
    src_disc = ProductSourceDiscoveryService(fetcher=fetcher)
    profile = ManufacturerProfile(
        manufacturer_id=mfg_name,
        canonical_name=mfg_name,
        verified_domains=tuple(c.domain for c in disc_res.candidates),
    )
    src_cands = src_disc.discover(prod, profile, candidate_urls=disc_res.search_result_urls)
    print(f"Source discovery candidates found: {len(src_cands)}")


if __name__ == "__main__":
    main()
