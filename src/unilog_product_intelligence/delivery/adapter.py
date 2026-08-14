"""Boundary from ProductTruth to the still-unavailable UniHack delivery contract."""

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


class UniHackDeliveryRecord(BaseModel):
    """A delivery-shaped record created only from an observed official contract."""

    model_config = ConfigDict(extra="forbid")

    headers: tuple[str, ...]
    values: dict[str, Any] = Field(default_factory=dict)

    def as_row(self) -> list[Any]:
        """Return values in the exact observed header order."""

        return [self.values.get(header) for header in self.headers]


class ProductTruthDeliveryAdapter:
    """Isolated adapter; exact field semantics remain pending the real delivery file."""

    def __init__(self, contract: DeliverySchemaContract) -> None:
        self.contract = contract

    def to_record(self, product: ProductTruth) -> UniHackDeliveryRecord:
        """Map only when the real header contract exists; do not invent official columns."""

        del product
        if not self.contract.available or not self.contract.headers:
            raise DeliveryMappingPending(
                "Exact UniHack delivery mapping is blocked until the official CSV is available."
            )
        raise DeliveryMappingPending(
            "Header contract is available, but field mappings require explicit contract review."
        )
