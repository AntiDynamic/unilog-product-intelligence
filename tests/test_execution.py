import pytest

from unilog_product_intelligence.application.execution import GeminiExecutionService
from unilog_product_intelligence.application.scale import (
    QuotaCircuitBreaker,
    QuotaGuard,
    SafetyBudget,
)
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse


class Provider429(RuntimeError):
    status_code = 429
    provider_code = "too_many_requests"


class FailingProvider(LLMProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        raise Provider429("quota")


class SuccessfulProvider(LLMProvider):
    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            output_text="{}",
            model="test",
            input_tokens=4,
            output_tokens=2,
            search_queries=("one", "two"),
        )


def test_execution_rolls_back_failed_reservation_and_opens_breaker() -> None:
    provider = FailingProvider()
    quota = QuotaGuard(SafetyBudget(max_rpm=10))
    breaker = QuotaCircuitBreaker(failure_threshold=2, cooldown_seconds=30)
    service = GeminiExecutionService(provider, quota=quota, breaker=breaker)

    for _ in range(2):
        with pytest.raises(Provider429):
            service.generate(LLMRequest(task="test", input_text="x"))

    assert breaker.state.value == "OPEN"
    assert provider.calls == 2
    assert quota.usage.input_tokens == 0
    assert quota.usage.search_queries == 0
    with pytest.raises(RuntimeError, match="circuit open"):
        service.generate(LLMRequest(task="test", input_text="x"))
    assert provider.calls == 2


def test_execution_commits_actual_usage_and_search_queries() -> None:
    quota = QuotaGuard(SafetyBudget(max_rpm=10))
    service = GeminiExecutionService(SuccessfulProvider(), quota=quota)

    response = service.generate(LLMRequest(task="test", input_text="x"))

    assert response.output_text == "{}"
    assert quota.usage.input_tokens == 4
    assert quota.usage.output_tokens == 2
    assert quota.usage.search_queries == 2
