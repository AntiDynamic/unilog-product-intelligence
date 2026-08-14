"""Mathematical fraction conversion, explicitly distinct from official lookup mappings."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction


class FractionSource(StrEnum):
    CALCULATED = "calculated"
    OFFICIAL_LOOKUP = "official_lookup"


@dataclass(frozen=True)
class FractionConversion:
    raw_value: str
    normalized_value: str
    source: FractionSource


def decimal_to_fraction(
    value: Decimal | str | float, max_denominator: int = 64
) -> FractionConversion:
    decimal = Decimal(str(value))
    fraction = Fraction(decimal).limit_denominator(max_denominator)
    return FractionConversion(
        str(value), f"{fraction.numerator}/{fraction.denominator}", FractionSource.CALCULATED
    )


def fraction_to_decimal(value: str) -> FractionConversion:
    fraction = Fraction(value.strip())
    return FractionConversion(
        value,
        format(Decimal(fraction.numerator) / Decimal(fraction.denominator), "f"),
        FractionSource.CALCULATED,
    )
