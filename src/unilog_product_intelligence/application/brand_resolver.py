"""Resolve real manufacturer and brand when Part_Manuf contains a distributor name.

Many rows in the UniHack dataset have Part_Manuf set to a distributor or co-op
(e.g. "Jam Industrial Supply LLC (JAMIN)", "Appliance Dealers Cooperative (APPDE)").
This module extracts the real manufacturer and brand from:

  1. A known distributor-code → manufacturer mapping (deterministic, zero network).
  2. Brand tokens found in Part_Desc (e.g. "3M 775L Stikit Film..." → "3M").
  3. The raw Part_Manuf string when it already contains a real manufacturer name.

No network calls are made; no values are invented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedIdentity:
    """Resolved manufacturer and brand after distributor masking is removed."""

    manufacturer: str
    """Canonical manufacturer name for DomainResolver lookup."""

    brand: str | None
    """Brand hint for DomainResolver brand-alias lookup (may equal manufacturer)."""

    resolution_method: str
    """How the identity was resolved.

    Values: 'distributor_map', 'desc_brand_token', 'raw_manuf', or 'unresolved'.
    """
    is_distributor: bool
    """True when Part_Manuf was identified as a distributor, not the real manufacturer."""


# ── Distributor code map ──────────────────────────────────────────────────────
# Maps known distributor abbreviation codes (extracted from the parenthetical
# suffix of Part_Manuf) to (manufacturer_key, brand_hint).
#
# manufacturer_key must match a key in DomainResolver._known_manufacturer_domains.
# brand_hint is the brand string to pass as `brand=` to DomainResolver.resolve().
#
# This list covers the most common distributors seen in the UniHack input dataset.
# _DISTRIBUTOR_CODE_MAP maps distributor code to (manufacturer_key, brand_hint)
_DISTRIBUTOR_CODE_MAP: dict[str, tuple[str | None, str | None]] = {
    # Jam Industrial Supply → 3M (abrasives)
    "JAMIN": ("3m", "3M"),
    # Appliance Dealers Cooperative → varies; brand extracted from description
    "APPDE": (None, None),
    # Mirka distributor code
    "MIRUS": ("mirka abrasives", "Mirka"),
    # Waxman Consumer Products Group
    "WAXMA": (None, None),
    # W.W. Grainger
    "GRNGR": (None, None),
    # HD Supply / Home Depot Supply
    "HDSUP": (None, None),
    # Interline Brands / Wilmar
    "ILINE": (None, None),
    # Johnstone Supply (HVAC)
    "JOHNS": (None, None),
    # Crescent Electric Supply
    "CRSNT": (None, None),
    # Ferguson Enterprises
    "FRGUS": (None, None),
    # MSC Industrial Direct
    "MSCID": (None, None),
    # Anixter International
    "ANXTR": (None, None),
    # Fastenal
    "FASTN": (None, None),
    # Lawson Products
    "LAWSN": (None, None),
    # True Value Company
    "TRVLU": (None, None),
    # Do it Best
    "DOIBT": (None, None),
    # Orgill
    "ORGLL": (None, None),
    # McLendon Hardware
    "MCLND": (None, None),
    # ABC Supply
    "ABCSP": (None, None),
    # Consolidated Electrical Distributors
    "CEDED": (None, None),
}


# ── Known brand tokens that appear in Part_Desc ───────────────────────────────
# Maps a normalized token (casefold) found in the description to the
# (manufacturer_key, canonical_brand) that DomainResolver recognises.
# Only include tokens that are unambiguous standalone brand identifiers.
_DESC_BRAND_TOKENS: list[tuple[str, str | None, str | None]] = [
    # (token_pattern, manufacturer_key, canonical_brand)
    (r"\b3[Mm]\b", "3m", "3M"),
    (r"\bDeWalt\b", "dewalt", "DeWalt"),
    (r"\bMilwaukee\b", "milwaukee", "Milwaukee"),
    (r"\bMilw\b", "milwaukee", "Milwaukee"),
    (r"\bMakita\b", "makita", "Makita"),
    (r"\bBosch\b", "bosch", "Bosch"),
    (r"\bRidgid\b", "ridgid", "Ridgid"),
    (r"\bDiablo\b", "diablo", "Diablo"),
    (r"\bFreud\b", "freud", "Freud"),
    (r"\bFestool\b", "festool", "Festool"),
    (r"\bMirka\b", "mirka", "Mirka"),
    (r"\bLeviton\b", "leviton", "Leviton"),
    (r"\bLutron\b", "lutron", "Lutron"),
    (r"\bHoneywell\b", "honeywell", "Honeywell"),
    (r"\bPhilips\b", "philips", "Philips"),
    (r"\bSatco\b", "satco", "Satco"),
    (r"\bKichler\b", "kichler", "Kichler"),
    (r"\bTrex\b", "trex", "Trex"),
    (r"\bTimberTech\b", "timbertech", "TimberTech"),
    (r"\bAzek\b", "azek", "Azek"),
    (r"\bFrigidaire\b", "frigidaire", "Frigidaire"),
    (r"\bWhirlpool\b", "whirlpool", "Whirlpool"),
    (r"\bRheem\b", "rheem", "Rheem"),
    (r"\bKohler\b", "kohler", "Kohler"),
    (r"\bMoen\b", "moen", "Moen"),
    (r"\bDelta\b", "delta", "Delta"),
    (r"\bSloan\b", "sloan", "Sloan"),
    (r"\bBradley\b", "bradley", "Bradley"),
    (r"\bBobrick\b", "bobrick", "Bobrick"),
    (r"\bHIOLIT\b", "mirka", "Mirka"),
    (r"\bCubitron\b", "3m", "3M"),
    (r"\bStikit\b", "3m", "3M"),
    (r"\bAbrasive[s]?\b", None, None),  # too generic; skip
    (r"\bStanley\b", "stanley", "Stanley"),
    (r"\bBlack\s*[&+]\s*Decker\b", "black decker", "Black & Decker"),
    (r"\bBlack\s*and\s*Decker\b", "black and decker", "Black & Decker"),
]

# Pre-compiled for performance
_COMPILED_BRAND_TOKENS: list[tuple[re.Pattern[str], str | None, str | None]] = [
    (re.compile(pattern, re.IGNORECASE), mfg_key, brand)
    for pattern, mfg_key, brand in _DESC_BRAND_TOKENS
]


# ── MPN prefix → brand mapping ────────────────────────────────────────────────
# When Part_Manuf is a distributor AND description contains no brand keyword,
# the leading characters of the MPN (manufacturer part number) often uniquely
# identify the brand.  Entries here are audited — every prefix corresponds to
# a publicly documented model-number range for that manufacturer.
#
# Tuple value: (manufacturer_key, canonical_brand)
# manufacturer_key must match a key in DomainResolver._known_manufacturer_domains.
_MPN_PREFIX_BRAND_MAP: dict[str, tuple[str, str]] = {
    # Frigidaire / Electrolux dishwashers and appliances
    "PDSH": ("frigidaire", "Frigidaire"),
    "FGID": ("frigidaire", "Frigidaire"),
    "FFID": ("frigidaire", "Frigidaire"),
    "FPHD": ("frigidaire", "Frigidaire"),
    "FGCD": ("frigidaire", "Frigidaire"),
    "FGBD": ("frigidaire", "Frigidaire"),
    "FGEI": ("frigidaire", "Frigidaire"),
    "FGEF": ("frigidaire", "Frigidaire"),
    "FGEW": ("frigidaire", "Frigidaire"),
    "FGEC": ("frigidaire", "Frigidaire"),
    "FPEH": ("frigidaire", "Frigidaire"),
    "FGHD": ("frigidaire", "Frigidaire"),
    # Whirlpool dishwashers and appliances
    "WDTS": ("whirlpool", "Whirlpool"),
    "WDTC": ("whirlpool", "Whirlpool"),
    "WDT": ("whirlpool", "Whirlpool"),
    "WRS": ("whirlpool", "Whirlpool"),
    "WRF": ("whirlpool", "Whirlpool"),
    "WFE": ("whirlpool", "Whirlpool"),
    "WFG": ("whirlpool", "Whirlpool"),
    "WMH": ("whirlpool", "Whirlpool"),
    "WML": ("whirlpool", "Whirlpool"),
    "WED": ("whirlpool", "Whirlpool"),
    "WFW": ("whirlpool", "Whirlpool"),
    # Maytag (Whirlpool brand)
    "MDB": ("maytag", "Maytag"),
    "MDT": ("maytag", "Maytag"),
    "MED": ("maytag", "Maytag"),
    "MFI": ("maytag", "Maytag"),
    "MFT": ("maytag", "Maytag"),
    "MGR": ("maytag", "Maytag"),
    # KitchenAid (Whirlpool brand)
    "KDTE": ("kitchenaid", "KitchenAid"),
    "KDTM": ("kitchenaid", "KitchenAid"),
    "KDFE": ("kitchenaid", "KitchenAid"),
    "KRFF": ("kitchenaid", "KitchenAid"),
    "KFGG": ("kitchenaid", "KitchenAid"),
    # GE Appliances & GE Profile
    "PTD70": ("ge appliances", "GE Profile"),
    "PTD": ("ge appliances", "GE Profile"),
    "PFD": ("ge appliances", "GE Profile"),
    "PFQ": ("ge appliances", "GE Profile"),
    "GDT": ("ge appliances", "GE"),
    "GDF": ("ge appliances", "GE"),
    "GDP": ("ge appliances", "GE"),
    "GTW": ("ge appliances", "GE"),
    "GFW": ("ge appliances", "GE"),
    "GFD": ("ge appliances", "GE"),
    "GUD": ("ge appliances", "GE"),
    "GSS": ("ge appliances", "GE"),
    # Rheem / Ruud water heaters and HVAC
    "XG40": ("rheem", "Rheem"),
    "XG50": ("rheem", "Rheem"),
    "PRSE": ("rheem", "Rheem"),
    "PROG": ("rheem", "Rheem"),
    "PROE": ("rheem", "Rheem"),
    "PROPH": ("rheem", "Rheem"),
    "ECH2": ("rheem", "Rheem"),
    # Samsung appliances
    "DW80": ("samsung", "Samsung"),
    "DW60": ("samsung", "Samsung"),
    "RF28": ("samsung", "Samsung"),
    "RF23": ("samsung", "Samsung"),
    "NE58": ("samsung", "Samsung"),
    "NE63": ("samsung", "Samsung"),
    # LG appliances (including WashTower WKE / WKEX / WKGX)
    "WKE100": ("lg", "LG"),
    "WKEX": ("lg", "LG"),
    "WKGX": ("lg", "LG"),
    "WKE": ("lg", "LG"),
    "LDT": ("lg", "LG"),
    "LDP": ("lg", "LG"),
    "LFXS": ("lg", "LG"),
    "LRMVS": ("lg", "LG"),
    "LRE": ("lg", "LG"),
    "LRG": ("lg", "LG"),
    "WT7": ("lg", "LG"),
    "WM9": ("lg", "LG"),
    "WM40": ("lg", "LG"),
    "WM34": ("lg", "LG"),
    "DLEX": ("lg", "LG"),
    "DLGX": ("lg", "LG"),
    # Speed Queen laundry
    "FF7011": ("speed queen", "Speed Queen"),
    "FF7": ("speed queen", "Speed Queen"),
    "FF": ("speed queen", "Speed Queen"),
    "TR7": ("speed queen", "Speed Queen"),
    "TC5": ("speed queen", "Speed Queen"),
    "DR7": ("speed queen", "Speed Queen"),
    "DC5": ("speed queen", "Speed Queen"),
    "DF7": ("speed queen", "Speed Queen"),
}


def _match_mpn_prefix(mpn: str) -> tuple[str, str] | None:
    """Return (mfg_key, brand) if the MPN starts with a known prefix, else None.

    Matches are tried longest-prefix-first to avoid false positives from
    shorter prefixes that are substrings of longer ones (e.g. 'WDT' vs 'WDTS').
    """
    mpn_upper = mpn.upper()
    for prefix in sorted(_MPN_PREFIX_BRAND_MAP, key=len, reverse=True):
        if mpn_upper.startswith(prefix):
            return _MPN_PREFIX_BRAND_MAP[prefix]
    return None


# ── Known distributor name fragments ─────────────────────────────────────────
# These substrings in Part_Manuf (case-insensitive) signal a distributor entity.
_DISTRIBUTOR_FRAGMENTS: tuple[str, ...] = (
    "supply",
    "dealer",
    "dealers",
    "cooperative",
    "co-op",
    "coop",
    "distributor",
    "distribution",
    "industrial",
    "wholesale",
    "warehouse",
    "lumber",
    "hardware",
    "electric supply",
    "electrical supply",
    "plumbing supply",
    "building supply",
    "direct supply",
    "janitor",
    "maintenance",
    "procurement",
    "appliance dealers",
    "builders firstsource",
    "boise cascade",
    "parksite",
    "u s lumber",
    "jam industrial",
    "l & w supply",
    "cameron ashley",
    "grainger",
    "ferguson",
    "fastenal",
    "orgill",
    "true value",
    "do it best",
    "abc supply",
)


class BrandManufacturerResolver:
    """Resolve the real manufacturer/brand when Part_Manuf is a distributor.

    Resolution priority:
      1. Extract parenthetical distributor code from Part_Manuf; look up in map.
      2. If code maps to a known manufacturer, return it.
      3. If code is a known distributor but no direct mapping, scan Part_Desc
         for known brand tokens.
      4. If no code, but Part_Manuf contains distributor-fragment keywords,
         scan Part_Desc for brand tokens.
      5. If Part_Manuf looks like a real manufacturer (no distributor signals),
         return it as-is (not a distributor).
    """

    def resolve(
        self,
        part_manuf: str | None,
        part_desc: str | None,
        *,
        mpn: str | None = None,
    ) -> ResolvedIdentity:
        """Resolve manufacturer and brand from raw input fields.

        Parameters
        ----------
        part_manuf:
            Raw Part_Manuf string, e.g. "Jam Industrial Supply LLC (JAMIN)".
        part_desc:
            Raw Part_Desc string, e.g. "3M 775L Stikit Film P150 - Cubitron II".
        mpn:
            Manufacturer part number, e.g. "PDSH4816AF".  Used as a last-resort
            brand signal when Part_Manuf is a distributor and description contains
            no brand keyword.  Optional and backwards-compatible.

        Returns
        -------
        ResolvedIdentity with manufacturer, brand, resolution_method, is_distributor.
        """
        manuf = (part_manuf or "").strip()
        desc = (part_desc or "").strip()

        # Step 1: Extract parenthetical code
        code = _extract_code(manuf)

        if code:
            mapping = _DISTRIBUTOR_CODE_MAP.get(code.upper())
            if mapping is not None:
                mfg_key, brand_hint = mapping
                if mfg_key:
                    # Known distributor with a direct manufacturer mapping
                    return ResolvedIdentity(
                        manufacturer=mfg_key,
                        brand=brand_hint,
                        resolution_method="distributor_map",
                        is_distributor=True,
                    )
                # Known distributor but no direct mapping — scan description first
                desc_result = _scan_desc_for_brand(desc)
                if desc_result:
                    mfg_from_desc, brand_from_desc = desc_result
                    return ResolvedIdentity(
                        manufacturer=mfg_from_desc,
                        brand=brand_from_desc,
                        resolution_method="desc_brand_token",
                        is_distributor=True,
                    )
                # Description scan yielded nothing — try MPN prefix
                if mpn:
                    mpn_result = _match_mpn_prefix(mpn)
                    if mpn_result:
                        mfg_from_mpn, brand_from_mpn = mpn_result
                        return ResolvedIdentity(
                            manufacturer=mfg_from_mpn,
                            brand=brand_from_mpn,
                            resolution_method="mpn_prefix",
                            is_distributor=True,
                        )
                # Distributor confirmed but can't resolve manufacturer
                return ResolvedIdentity(
                    manufacturer=_strip_code(manuf),
                    brand=None,
                    resolution_method="unresolved",
                    is_distributor=True,
                )
            # Code present but not in our map; still check if name sounds like distributor
            if _looks_like_distributor(manuf):
                desc_result = _scan_desc_for_brand(desc)
                if desc_result:
                    mfg_from_desc, brand_from_desc = desc_result
                    return ResolvedIdentity(
                        manufacturer=mfg_from_desc,
                        brand=brand_from_desc,
                        resolution_method="desc_brand_token",
                        is_distributor=True,
                    )
                if mpn:
                    mpn_result = _match_mpn_prefix(mpn)
                    if mpn_result:
                        mfg_from_mpn, brand_from_mpn = mpn_result
                        return ResolvedIdentity(
                            manufacturer=mfg_from_mpn,
                            brand=brand_from_mpn,
                            resolution_method="mpn_prefix",
                            is_distributor=True,
                        )
        else:
            # No parenthetical code — check distributor fragment heuristic
            if _looks_like_distributor(manuf):
                desc_result = _scan_desc_for_brand(desc)
                if desc_result:
                    mfg_from_desc, brand_from_desc = desc_result
                    return ResolvedIdentity(
                        manufacturer=mfg_from_desc,
                        brand=brand_from_desc,
                        resolution_method="desc_brand_token",
                        is_distributor=True,
                    )
                if mpn:
                    mpn_result = _match_mpn_prefix(mpn)
                    if mpn_result:
                        mfg_from_mpn, brand_from_mpn = mpn_result
                        return ResolvedIdentity(
                            manufacturer=mfg_from_mpn,
                            brand=brand_from_mpn,
                            resolution_method="mpn_prefix",
                            is_distributor=True,
                        )

        # Step 5: Part_Manuf looks like a real manufacturer — use as-is,
        # but also extract brand from description if present
        clean_manuf = _strip_code(manuf) or manuf
        desc_result = _scan_desc_for_brand(desc)
        brand_val: str | None = desc_result[1] if desc_result else None
        return ResolvedIdentity(
            manufacturer=clean_manuf,
            brand=brand_val,
            resolution_method="raw_manuf",
            is_distributor=False,
        )



# ── Internal helpers ──────────────────────────────────────────────────────────


def _extract_code(manuf: str) -> str | None:
    """Extract the parenthetical code, e.g. 'JAMIN' from 'Jam Industrial... (JAMIN)'."""
    match = re.search(r"\(([A-Z0-9]{2,12})\)\s*$", manuf.strip())
    if match:
        return match.group(1)
    # Also handle numeric suffixes like "Freud Inc (2435)" — those are account numbers, skip
    match = re.search(r"\(([A-Za-z][A-Za-z0-9]{1,11})\)\s*$", manuf.strip())
    if match:
        code = match.group(1)
        # Only return if it looks like an alphabetic code (not a pure number)
        if re.search(r"[A-Za-z]{2,}", code):
            return code.upper()
    return None


def _strip_code(manuf: str) -> str:
    """Remove the parenthetical suffix from a Part_Manuf string."""
    return re.sub(r"\s*\([^)]{2,15}\)\s*$", "", manuf).strip()


def _looks_like_distributor(manuf: str) -> bool:
    """Return True when the manuf string contains known distributor signals."""
    lower = manuf.casefold()
    return any(fragment in lower for fragment in _DISTRIBUTOR_FRAGMENTS)


def _scan_desc_for_brand(desc: str) -> tuple[str, str] | None:
    """Scan Part_Desc for a known brand token and return (mfg_key, brand).

    Returns None if no brand token is found or the match has no manufacturer mapping.
    """
    for pattern, mfg_key, brand in _COMPILED_BRAND_TOKENS:
        if mfg_key is None:
            continue
        if pattern.search(desc):
            return (mfg_key, brand or mfg_key)
    return None
