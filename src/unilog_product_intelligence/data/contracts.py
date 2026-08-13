"""Typed contracts for the data foundation.

These contracts describe source data and ingestion state without turning the external delivery
CSV into the internal product domain model.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FileFormat(StrEnum):
    """Tabular formats supported by the Phase 1 reader layer."""

    CSV = "csv"
    XLSX = "xlsx"
    DOCX = "docx"
    PDF = "pdf"


class NormalizedValue(BaseModel):
    """A source value plus its deterministic normalization result and reason."""

    model_config = ConfigDict(extra="forbid")

    raw_value: Any = None
    normalized_value: str | None = None
    reason: str | None = None


class SourceFile(BaseModel):
    """Immutable metadata about one source file."""

    model_config = ConfigDict(extra="forbid")

    path: str
    name: str
    format: FileFormat
    available: bool
    size_bytes: int | None = None
    sha256: str | None = None


class ColumnDefinition(BaseModel):
    """Observed column metadata from a source sheet or delivery contract."""

    model_config = ConfigDict(extra="forbid")

    position: int
    name: str
    non_null_count: int = 0
    unique_count: int = 0
    detected_types: list[str] = Field(default_factory=list)


class SheetInspection(BaseModel):
    """Observed worksheet or CSV table structure."""

    model_config = ConfigDict(extra="forbid")

    name: str
    header_row_index: int
    headers: list[str]
    row_count: int
    column_count: int
    merged_ranges: list[str] = Field(default_factory=list)
    leading_rows: list[list[Any]] = Field(default_factory=list)
    columns: list[ColumnDefinition] = Field(default_factory=list)


class DatasetRow(BaseModel):
    """One source row with raw values and field-level normalization provenance."""

    model_config = ConfigDict(extra="forbid")

    row_number: int
    raw_values: dict[str, Any]
    normalized_values: dict[str, str | None]
    normalization: dict[str, NormalizedValue]
    row_hash: str


class DatasetInspection(BaseModel):
    """Computed quality metrics for one observed tabular dataset."""

    model_config = ConfigDict(extra="forbid")

    source_file: SourceFile
    sheets: list[SheetInspection]
    row_count: int
    column_count: int
    null_counts: dict[str, int] = Field(default_factory=dict)
    placeholder_counts: dict[str, int] = Field(default_factory=dict)
    unique_counts: dict[str, int] = Field(default_factory=dict)
    duplicate_row_count: int = 0
    representative_values: dict[str, list[str]] = Field(default_factory=dict)
    detected_data_types: dict[str, list[str]] = Field(default_factory=dict)


class DataInventory(BaseModel):
    """Machine-readable inventory for expected files, including unavailable files."""

    model_config = ConfigDict(extra="forbid")

    data_root: str
    expected_files: list[str]
    files: list[DatasetInspection | SourceFile]
    available_file_count: int
    unavailable_file_count: int


class IngestionResult(BaseModel):
    """Result of one idempotent ingestion attempt."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    idempotency_key: str
    created: bool
    source_file: SourceFile
    row_count: int
    sheet_names: list[str]
    rows: list[DatasetRow] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Deterministic validation report for an external delivery file."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    expected_headers: list[str]
    observed_headers: list[str]
    missing_headers: list[str] = Field(default_factory=list)
    unexpected_headers: list[str] = Field(default_factory=list)
    duplicate_headers: list[str] = Field(default_factory=list)
    order_changed: bool = False
    invalid_row_widths: dict[int, int] = Field(default_factory=dict)
