"""Generated dataset inventory and quality metrics."""

from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .contracts import (
    ColumnDefinition,
    DataInventory,
    DatasetInspection,
    FileFormat,
    SourceFile,
)
from .normalize import PLACEHOLDER_VALUES
from .readers import read_tabular_file

EXPECTED_UNILOG_FILES = (
    "Unihack_ Sample Dataset - Input.csv",
    "Unihack_ Expected Output - Delivery Format.csv",
    "Sample-1000_Items.xlsx",
    "Unilog-Sample_200_Items-Input-vs-Output.xlsx",
    "UNILOG_INTERNAL_CONTENT_GUIDELINES.docx",
    "Unilog_Master_UOM_Standards_Abbreviations_and_Terms.xlsx",
    "Decimal_Fraction.xlsx",
    "UniCat_Manufacturer_and_Brand_List.xlsx",
    "Unicat_Lov_v1_0_Updated_With_Remarks.xlsx",
    "FAUCETS_LOV.xlsx",
    "Fittings_LOV.xlsx",
    "Reference_Documents_Summary.xlsx",
)


def _is_null(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _detected_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (datetime, date)):
        return "date"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    text = str(value).strip()
    try:
        int(text)
        return "integer"
    except ValueError:
        try:
            float(text)
            return "number"
        except ValueError:
            return "string"


def _inspect_dataset(path: Path) -> DatasetInspection:
    result = read_tabular_file(path)
    rows = result.rows
    headers = result.sheets[0].headers if result.sheets else []
    null_counts = {header: 0 for header in headers}
    placeholder_counts = {header: 0 for header in headers}
    values_by_column: dict[str, list[Any]] = {header: [] for header in headers}
    types_by_column: dict[str, set[str]] = {header: set() for header in headers}
    row_signatures: Counter[str] = Counter()
    for row in rows:
        row_signatures[row.row_hash] += 1
        for header in headers:
            raw = row.raw_values.get(header)
            if _is_null(raw):
                null_counts[header] += 1
                continue
            values_by_column[header].append(raw)
            types_by_column[header].add(_detected_type(raw))
            if str(raw).strip() in PLACEHOLDER_VALUES:
                placeholder_counts[header] += 1
    unique_counts = {
        header: len({str(value) for value in values}) for header, values in values_by_column.items()
    }
    representatives = {
        header: [str(value) for value in list(dict.fromkeys(values))[:5]]
        for header, values in values_by_column.items()
    }
    columns = [
        ColumnDefinition(
            position=index,
            name=header,
            non_null_count=len(values_by_column[header]),
            unique_count=unique_counts[header],
            detected_types=sorted(types_by_column[header]),
        )
        for index, header in enumerate(headers, start=1)
    ]
    sheets = [sheet.model_copy(update={"columns": columns}) for sheet in result.sheets]
    return DatasetInspection(
        source_file=result.source_file,
        sheets=sheets,
        row_count=len(rows),
        column_count=len(headers),
        null_counts=null_counts,
        placeholder_counts=placeholder_counts,
        unique_counts=unique_counts,
        duplicate_row_count=sum(count - 1 for count in row_signatures.values() if count > 1),
        representative_values=representatives,
        detected_data_types={header: sorted(types_by_column[header]) for header in headers},
    )


def build_inventory(
    data_root: str | Path, expected_files: Iterable[str] = EXPECTED_UNILOG_FILES
) -> DataInventory:
    """Inspect expected files without inventing missing sources or metrics."""

    root = Path(data_root)
    expected = list(expected_files)
    reports: list[DatasetInspection | SourceFile] = []
    for name in expected:
        path = root / name
        if path.is_file() and path.suffix.lower() in {".csv", ".xlsx"}:
            reports.append(_inspect_dataset(path))
        elif path.is_file():
            reports.append(
                SourceFile(
                    path=str(path),
                    name=path.name,
                    format=FileFormat(
                        {".csv": "csv", ".xlsx": "xlsx", ".docx": "docx", ".pdf": "pdf"}.get(
                            path.suffix.lower(), "csv"
                        )
                    ),
                    available=True,
                    size_bytes=path.stat().st_size,
                )
            )
        else:
            reports.append(
                SourceFile(
                    path=str(path),
                    name=name,
                    format=FileFormat(
                        {".csv": "csv", ".xlsx": "xlsx", ".docx": "docx", ".pdf": "pdf"}.get(
                            Path(name).suffix.lower(), "xlsx"
                        )
                    ),
                    available=False,
                )
            )
    available = sum(
        report.source_file.available if isinstance(report, DatasetInspection) else report.available
        for report in reports
    )
    return DataInventory(
        data_root=str(root),
        expected_files=expected,
        files=reports,
        available_file_count=available,
        unavailable_file_count=len(reports) - available,
    )
