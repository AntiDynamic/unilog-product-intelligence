from fastapi.testclient import TestClient

from unilog_product_intelligence.api import create_app


def test_health_endpoint_is_operational_only() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
