"""Tests for bounded concurrency, rate limiting, ordered streaming, and failure isolation."""

from __future__ import annotations

import concurrent.futures
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from scripts.run_pipeline import (
    _process_row_job,
    _RowExecutionResult,
    _RowJob,
)

from unilog_product_intelligence.application.phase65 import (
    Phase65Pipeline,
    Phase65Result,
    Phase65Status,
)
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.delivery.adapter import (
    Phase65ResultDeliveryAdapter,
    UniHackDeliveryRecord,
)
from unilog_product_intelligence.domain.truth import ProductTruth
from unilog_product_intelligence.enrichment.models import ReferenceAvailability
from unilog_product_intelligence.enrichment.reference import ReferencePack
from unilog_product_intelligence.providers.gemini import GeminiConcurrencyLimiter
from unilog_product_intelligence.retrieval.core import (
    CacheStatus,
    DomainCircuitBreaker,
    FetchResult,
    SourceCache,
    SourceDecision,
    SourceKind,
    SourceRecord,
)


def test_gemini_concurrency_limiter_bounds() -> None:
    """Verify GeminiConcurrencyLimiter strictly enforces max_concurrency."""
    max_concurrency = 3
    total_threads = 15
    limiter = GeminiConcurrencyLimiter(max_concurrency=max_concurrency)

    active_count = 0
    active_lock = threading.Lock()
    max_active_observed = 0

    def _worker() -> None:
        nonlocal active_count, max_active_observed
        with limiter:
            with active_lock:
                active_count += 1
                if active_count > max_active_observed:
                    max_active_observed = active_count
            time.sleep(0.02)
            with active_lock:
                active_count -= 1

    threads = [threading.Thread(target=_worker) for _ in range(total_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_active_observed <= max_concurrency
    assert limiter.peak_concurrency <= max_concurrency
    assert limiter.total_requests == total_threads


def test_source_cache_and_circuit_breaker_thread_safety() -> None:
    """Verify SourceCache and DomainCircuitBreaker remain consistent across concurrent threads."""
    cache = SourceCache()
    breaker = DomainCircuitBreaker(max_consecutive_failures=3)

    def _cache_worker(idx: int) -> None:
        url = f"https://example.com/item/{idx % 5}"
        source_rec = SourceRecord(
            canonical_url=url,
            original_url=url,
            source_kind=SourceKind.MANUFACTURER_PRODUCT_PAGE,
            decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
            manufacturer_id="test-mfg",
            manufacturer_domain="example.com",
            product_id="test-prod",
            fetched_at=datetime.now(UTC),
        )
        res = FetchResult(
            source=source_rec,
            cache_status=CacheStatus.MISS,
            body=b"<html>ok</html>",
            latency_ms=10,
        )
        cache.put(res)
        cached = cache.get(url)
        assert cached is not None
        assert cached.body == b"<html>ok</html>"

    def _breaker_worker(idx: int) -> None:
        domain = f"domain{idx % 4}.com"
        breaker.record_failure(domain, "timeout")
        _ = breaker.is_available(domain)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futs = []
        for i in range(40):
            futs.append(executor.submit(_cache_worker, i))
            futs.append(executor.submit(_breaker_worker, i))
        for f in futs:
            f.result()

    assert len(cache) <= 5


def test_process_row_job_concurrency_and_ordering() -> None:
    """Verify concurrent worker execution preserves strict row ordering and isolates errors."""
    mock_pipeline = MagicMock(spec=Phase65Pipeline)
    mock_truth = MagicMock(spec=ProductTruthService)
    mock_adapter = MagicMock(spec=Phase65ResultDeliveryAdapter)
    mock_ref_pack = ReferencePack(availability=ReferenceAvailability.REFERENCE_AVAILABLE)

    # Configure mock delivery record
    headers = [f"col_{i}" for i in range(252)]
    mock_delivery = MagicMock(spec=UniHackDeliveryRecord)
    mock_delivery.as_row.return_value = ["val"] * 252
    mock_adapter.to_record.return_value = mock_delivery

    active_workers = 0
    worker_lock = threading.Lock()
    peak_workers = 0

    def _side_effect_run(product: Any) -> Phase65Result:
        nonlocal active_workers, peak_workers
        with worker_lock:
            active_workers += 1
            if active_workers > peak_workers:
                peak_workers = active_workers

        # Row 3 will raise an exception to test failure isolation
        if product.product_id == "row-3":
            with worker_lock:
                active_workers -= 1
            raise ValueError("Simulated product failure on row 3")

        # Variable sleep to test out-of-order completion
        if product.product_id == "row-1":
            time.sleep(0.08)
        else:
            time.sleep(0.01)

        with worker_lock:
            active_workers -= 1

        mock_res = MagicMock(spec=Phase65Result)
        mock_res.status = Phase65Status.ENRICHED
        mock_res.blocker = None
        mock_res.phase4_job = None
        mock_res.discovery = None
        mock_res.manufacturer_job = None
        mock_res.enrichment = None
        mock_truth_obj = MagicMock(spec=ProductTruth)
        mock_truth_obj.identity = None
        mock_truth_obj.sources = ()
        mock_truth_obj.evidence = ()
        mock_truth_obj.digital_assets = ()
        mock_res.product_truth = mock_truth_obj
        return mock_res

    mock_pipeline.run.side_effect = _side_effect_run

    def _mock_create(pid: str, raw: Any, src: Any) -> Any:
        m = MagicMock()
        m.product_id = pid
        return m

    mock_truth.create_from_raw_input.side_effect = _mock_create

    # Prepare 6 mock input rows
    num_rows = 6
    mock_rows = []
    for i in range(1, num_rows + 1):
        r = MagicMock()
        r.row_number = i
        r.raw_values = {"Mfg_Part_Num": f"MPN-{i}", "Part_Manuf": f"MANUF-{i}"}
        mock_rows.append(r)

    # Run in concurrent executor matching run_pipeline architecture
    completed_buffer: dict[int, _RowExecutionResult] = {}
    in_flight_futures: dict[int, concurrent.futures.Future[_RowExecutionResult]] = {}
    next_write_idx = 1
    written_rows: list[list[Any]] = []
    traces: list[dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=4, thread_name_prefix="test-worker"
    ) as executor:
        for idx, row in enumerate(mock_rows, start=1):
            job = _RowJob(
                idx=idx,
                row=row,
                queued_at=datetime.now(UTC),
                queued_perf=time.perf_counter(),
            )
            fut = executor.submit(
                _process_row_job,
                job,
                mock_pipeline,
                mock_truth,
                mock_adapter,
                headers,
                "live-deterministic",
                "test-model",
                mock_ref_pack,
            )
            in_flight_futures[idx] = fut

        while in_flight_futures:
            done, _ = concurrent.futures.wait(
                in_flight_futures.values(),
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for fut in done:
                done_idx = next(k for k, v in in_flight_futures.items() if v is fut)
                del in_flight_futures[done_idx]
                res = fut.result()
                completed_buffer[res.idx] = res

            while next_write_idx in completed_buffer:
                res = completed_buffer.pop(next_write_idx)
                written_rows.append(res.delivery_row)
                traces.append(res.trace)
                next_write_idx += 1

    # 1. Verify concurrency actually occurred and respected worker bounds
    assert 1 < peak_workers <= 4

    # 2. Verify all rows were written in exact order 1..6
    assert len(written_rows) == num_rows
    assert len(traces) == num_rows
    assert [t["row_index"] for t in traces] == [1, 2, 3, 4, 5, 6]

    # 3. Verify failure isolation on row 3
    # Row 3 should be empty 252-column row with error trace
    assert written_rows[2] == [None] * 252
    assert traces[2]["final_status"] == "ERROR"
    assert "Simulated product failure on row 3" in traces[2]["error"]

    # Other rows should have full valid records
    assert written_rows[0] == ["val"] * 252
    assert written_rows[1] == ["val"] * 252
    assert written_rows[3] == ["val"] * 252

    # 4. Verify telemetry fields exist in traces
    for t in traces:
        assert "worker_id" in t
        assert "queued_at" in t
        assert "started_at" in t
        assert "completed_at" in t
        assert "queue_wait_ms" in t
        assert "execution_ms" in t


def test_delivery_contract_252_columns_preserved() -> None:
    """Verify delivery contract is loaded and output preserves exactly 252 columns."""
    from unilog_product_intelligence.delivery.adapter import DeliverySchemaContract

    schema_file = (
        Path(__file__).resolve().parent.parent / "docs" / "research" / "delivery-schema.json"
    )
    if not schema_file.exists():
        pytest.skip("Delivery schema json not found")

    contract = DeliverySchemaContract.from_json(schema_file)
    assert contract.available
    assert len(contract.headers) == 252

    # Verify adapter uses exactly the 252 headers
    adapter = Phase65ResultDeliveryAdapter(contract)
    assert len(adapter.contract.headers) == 252
