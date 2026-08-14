from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "unilog_product_intelligence"


def test_google_sdk_imports_are_confined_to_provider_boundary() -> None:
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts or path.name == "gemini.py":
            continue
        if "google.genai" in path.read_text(encoding="utf-8"):
            violations.append(str(path))
    assert violations == []


def test_execution_service_contains_quota_and_breaker() -> None:
    source = (SRC / "application" / "execution.py").read_text(encoding="utf-8")
    assert "QuotaGuard" in source
    assert "QuotaCircuitBreaker" in source
