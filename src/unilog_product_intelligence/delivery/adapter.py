"""Boundary from ProductTruth to the observed UniHack delivery contract."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.domain.truth import ProductTruth


class DeliveryMappingPending(RuntimeError):
    """Raised when exact official delivery headers are unavailable."""


class DeliverySchemaContract(BaseModel):
    """Observed official header contract; empty means mapping is intentionally blocked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool = False
    source_file: str | None = None
    headers: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, path: str | Path) -> "DeliverySchemaContract":
        """Load an exact header contract extracted from the supplied template."""

        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        headers = tuple(payload.get("headers", ()))
        return cls(
            available=bool(headers),
            source_file=str(payload.get("source_file", source)),
            headers=headers,
        )


class UniHackDeliveryRecord(BaseModel):
    """A delivery-shaped record created only from an observed official contract."""

    model_config = ConfigDict(extra="forbid")

    headers: tuple[str, ...]
    values: dict[str, Any] = Field(default_factory=dict)

    def as_row(self) -> list[Any]:
        """Return values in the exact observed header order."""

        return [self.values.get(header) for header in self.headers]


class ProductTruthDeliveryAdapter:
    """Isolated adapter that maps only source fields sharing observed headers."""

    def __init__(self, contract: DeliverySchemaContract) -> None:
        self.contract = contract

    def to_record(self, product: ProductTruth) -> UniHackDeliveryRecord:
        """Map raw source values only when their names occur in the observed contract."""

        if not self.contract.available or not self.contract.headers:
            raise DeliveryMappingPending(
                "Exact UniHack delivery mapping is blocked until the official CSV is available."
            )
        values = {
            field.field_name: field.raw_value
            for field in product.raw_inputs
            if field.field_name in self.contract.headers
        }
        return UniHackDeliveryRecord(headers=self.contract.headers, values=values)
