"""Audit locally mounted UniHack/reference files without copying their contents."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from unilog_product_intelligence.data.inventory import EXPECTED_UNILOG_FILES
from unilog_product_intelligence.data.readers import read_tabular_file


def audit(roots: tuple[Path, ...]) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for name in EXPECTED_UNILOG_FILES:
        path = _find(name, roots)
        files.append(_audit_file(name, path, roots))
    available = sum(bool(item["available"]) for item in files)
    reference_files = [item for item in files if item["kind"] == "reference"]
    available_references = sum(bool(item["available"]) for item in reference_files)
    return {
        "audit_version": "phase6-reference-audit-v1",
        "roots_scanned": [_scope(root, roots[0]) for root in roots],
        "expected_file_count": len(files),
        "available_file_count": available,
        "unavailable_file_count": len(files) - available,
        "available_reference_file_count": available_references,
        "unavailable_reference_file_count": len(reference_files) - available_references,
        "files": files,
        "reference_pack_status": (
            "REFERENCE_AVAILABLE" if available_references else "REFERENCE_UNAVAILABLE"
        ),
    }


def _find(name: str, roots: tuple[Path, ...]) -> Path | None:
    for root in roots:
        direct = root / name
        if direct.is_file():
            return direct
        for path in root.rglob(name):
            if any(
                part in {".git", ".venv", "__pycache__", ".pytest_cache"} for part in path.parts
            ):
                continue
            if path.is_file():
                return path
    return None


def _audit_file(name: str, path: Path | None, roots: tuple[Path, ...]) -> dict[str, object]:
    kind = (
        "working_input"
        if name.startswith("Unihack_ Sample")
        else "delivery_contract"
        if name.startswith("Unihack_ Expected")
        else "reference"
    )
    result: dict[str, object] = {
        "name": name,
        "kind": kind,
        "available": path is not None,
        "path_scope": _scope(path, roots[0]) if path else None,
        "size_bytes": path.stat().st_size if path else None,
        "sha256": _sha256(path) if path else None,
        "parser_status": "unavailable" if path is None else "pending",
        "validation_status": "unavailable" if path is None else "pending",
        "sheets": [],
        "rows": None,
        "columns": None,
        "errors": [] if path else ["file_not_found_in_scanned_roots"],
    }
    if path is None:
        return result
    try:
        if path.suffix.casefold() in {".csv", ".xlsx"}:
            read = read_tabular_file(path)
            result["parser_status"] = "ok"
            result["sheets"] = [
                {
                    "name": sheet.name,
                    "rows": sheet.row_count,
                    "columns": sheet.column_count,
                    "headers": sheet.headers,
                }
                for sheet in read.sheets
            ]
            result["rows"] = len(read.rows)
            result["columns"] = read.sheets[0].column_count if read.sheets else 0
            widths = _csv_widths(path) if path.suffix.casefold() == ".csv" else ()
            errors = result["errors"]
            if isinstance(errors, list) and widths:
                expected = widths[0]
                invalid = [width for width in widths[1:] if width != expected]
                if invalid:
                    errors.append(f"invalid_row_widths:{len(invalid)}")
            result["validation_status"] = "passed" if not result["errors"] else "failed"
        elif path.suffix.casefold() == ".docx":
            with ZipFile(path) as archive:
                if "[Content_Types].xml" not in archive.namelist():
                    raise ValueError("not_a_docx_package")
            result["parser_status"] = "package_verified"
            result["validation_status"] = "metadata_only"
        else:
            result["parser_status"] = "hash_only"
            result["validation_status"] = "metadata_only"
    except (OSError, BadZipFile, ValueError) as error:
        result["parser_status"] = "failed"
        result["validation_status"] = "failed"
        errors = result["errors"]
        if isinstance(errors, list):
            errors.append(type(error).__name__)
    return result


def _csv_widths(path: Path) -> tuple[int, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(len(row) for row in csv.reader(handle))


def _sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _scope(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return f"external-root/{path.name}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit mounted UniHack/reference files")
    parser.add_argument("--root", action="append", type=Path, default=[])
    parser.add_argument(
        "--output", type=Path, default=Path("docs/research/reference-pack-audit.json")
    )
    args = parser.parse_args()
    roots = tuple(args.root or [Path.cwd(), Path.cwd() / "data" / "external"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit(roots), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Reference audit written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
