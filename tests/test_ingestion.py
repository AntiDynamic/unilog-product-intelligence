from pathlib import Path

from unilog_product_intelligence.data.ingestion import IngestionService


def test_ingestion_is_idempotent_for_same_dataset_and_content(tmp_path: Path) -> None:
    source = tmp_path / "metadata.csv"
    source.write_text("field_a,field_b\nvalue-a,value-b\n", encoding="utf-8")
    service = IngestionService()

    first = service.ingest(source, dataset_name="metadata")
    second = service.ingest(source, dataset_name="metadata")

    assert first.created is True
    assert second.created is False
    assert first.run_id == second.run_id
    assert first.idempotency_key == second.idempotency_key
    assert second.row_count == 1
