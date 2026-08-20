"""Golden fixture cases for product truth and invariant verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GoldenProductCase:
    """Expected truth contract for a golden product test case."""

    product_id: str
    mpn: str
    manufacturer: str
    brand: str
    expected_attributes: dict[str, Any]
    expected_evidence_count: int = 1
    expected_canonical_domain: str = ""
    description_keywords: tuple[str, ...] = ()


GOLDEN_CASES: tuple[GoldenProductCase, ...] = (
    GoldenProductCase(
        product_id="golden-dewalt-planer",
        mpn="DW735X",
        manufacturer="DEWALT",
        brand="DEWALT",
        expected_attributes={
            "Amps": "15 A",
            "No Load Speed": "20000/10000 RPM",
            "Depth Capacity": "6 in",
            "Width Capacity": "13 in",
        },
        expected_evidence_count=1,
        expected_canonical_domain="dewalt.com",
        description_keywords=("planer", "two-speed", "knives"),
    ),
    GoldenProductCase(
        product_id="golden-milwaukee-drill",
        mpn="2804-20",
        manufacturer="Milwaukee",
        brand="Milwaukee",
        expected_attributes={
            "Voltage": "18V",
            "Peak Torque": "1200 in-lbs",
            "RPM": "0-550 / 0-2,000 RPM",
            "BPM": "32,000 BPM",
        },
        expected_evidence_count=1,
        expected_canonical_domain="milwaukeetool.com",
        description_keywords=("hammer", "drill", "fuel", "brushless"),
    ),
    GoldenProductCase(
        product_id="golden-3m-tape",
        mpn="DCB518ASTS06G",
        manufacturer="3M",
        brand="3M",
        expected_attributes={
            "Color": "Amber",
            "Backing Material": "Polyimide",
        },
        expected_evidence_count=1,
        expected_canonical_domain="3m.com",
        description_keywords=("tape", "polyimide", "film"),
    ),
)

__all__ = ["GOLDEN_CASES", "GoldenProductCase"]
