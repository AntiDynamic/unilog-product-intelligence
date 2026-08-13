"""Real-data ingestion, normalization, inventory, and contract validation."""

from .contracts import (
    ColumnDefinition,
    DataInventory,
    DatasetRow,
    FileFormat,
    IngestionResult,
    NormalizedValue,
    SourceFile,
    ValidationResult,
)
from .delivery import extract_delivery_schema, validate_delivery_csv
from .ingestion import IngestionService, InMemoryIngestionRegistry
from .normalize import PLACEHOLDER_VALUES, normalize_row, normalize_value
from .readers import read_tabular_file

__all__ = [
    "ColumnDefinition",
    "DataInventory",
    "DatasetRow",
    "FileFormat",
    "InMemoryIngestionRegistry",
    "IngestionResult",
    "IngestionService",
    "NormalizedValue",
    "PLACEHOLDER_VALUES",
    "SourceFile",
    "ValidationResult",
    "extract_delivery_schema",
    "normalize_row",
    "normalize_value",
    "read_tabular_file",
    "validate_delivery_csv",
]
