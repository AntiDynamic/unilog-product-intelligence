"""Idempotent ingestion orchestration over format-specific readers."""

import hashlib
from collections.abc import MutableMapping
from pathlib import Path

from .contracts import IngestionResult
from .readers import read_tabular_file


class InMemoryIngestionRegistry:
    """Small deterministic registry used by unit tests and local dry runs.

    PostgreSQL persistence is defined in ``database/schema.sql``; this registry keeps the
    orchestration testable without introducing a second persistence abstraction prematurely.
    """

    def __init__(self) -> None:
        self._runs: MutableMapping[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._runs.get(key)

    def put(self, key: str, run_id: str) -> None:
        self._runs[key] = run_id


class IngestionService:
    """Read a source file once per content identity and return raw plus normalized rows."""

    def __init__(self, registry: InMemoryIngestionRegistry | None = None) -> None:
        self.registry = registry or InMemoryIngestionRegistry()

    def ingest(self, path: str | Path, dataset_name: str | None = None) -> IngestionResult:
        read_result = read_tabular_file(path)
        name = dataset_name or read_result.source_file.name
        digest = hashlib.sha256(f"{name}:{read_result.source_file.sha256}".encode()).hexdigest()
        run_id = f"run-{digest[:32]}"
        prior = self.registry.get(digest)
        created = prior is None
        if created:
            self.registry.put(digest, run_id)
        return IngestionResult(
            run_id=prior or run_id,
            idempotency_key=digest,
            created=created,
            source_file=read_result.source_file,
            row_count=len(read_result.rows),
            sheet_names=[sheet.name for sheet in read_result.sheets],
            rows=read_result.rows,
        )
