"""Single controlled execution boundary for all Gemini provider calls."""

from __future__ import annotations

from typing import Any, cast

from unilog_product_intelligence.application.scale import (
    QuotaCircuitBreaker,
    QuotaGuard,
    Usage,
    estimate_context_tokens,
)
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse


class GeminiExecutionService(LLMProvider):
    """Routes provider calls through quota and circuit controls."""

    def __init__(
        self,
        provider: LLMProvider,
        quota: QuotaGuard | None = None,
        breaker: QuotaCircuitBreaker | None = None,
    ) -> None:
        self.provider = provider
        self.quota = quota or QuotaGuard()
        self.breaker = breaker or QuotaCircuitBreaker()

    def generate(self, request: LLMRequest) -> LLMResponse:
        return self._execute(request, None)

    def generate_with_tools(self, request: LLMRequest, tools: list[dict[str, Any]]) -> LLMResponse:
        return self._execute(request, tools)

    def _execute(self, request: LLMRequest, tools: list[dict[str, Any]] | None) -> LLMResponse:
        if not self.breaker.allow():
            raise RuntimeError("Gemini execution deferred: circuit open")
        estimated_search_queries = int(
            any(tool.get("type") == "google_search" for tool in tools or [])
        )
        guard, reservation = self.quota.reserve_before_execution(
            estimated_input_tokens=estimate_context_tokens(request.input_text),
            estimated_search_queries=estimated_search_queries,
        )
        if reservation is None:
            raise RuntimeError(f"Gemini execution deferred: {guard.reason}")
        try:
            if tools is not None and callable(getattr(self.provider, "generate_with_tools", None)):
                response = cast(LLMResponse, self.provider.generate_with_tools(request, tools))  # type: ignore[attr-defined]
            else:
                response = self.provider.generate(request)
        except Exception as error:
            self.quota.rollback(reservation)
            if _is_429(error):
                self.breaker.record_429(retry_after_seconds=_retry_after_seconds(error))
            raise
        self.quota.commit(reservation, Usage(
            input_tokens=response.input_tokens or 0,
            output_tokens=response.output_tokens or 0,
            cached_tokens=response.cached_tokens or 0,
            search_queries=len(response.search_queries),
            cost_usd=response.estimated_cost_usd or 0.0,
        ))
        self.breaker.record_success()
        return response


def _is_429(error: BaseException) -> bool:
    status_code = getattr(error, "status_code", None)
    return status_code == 429 or str(status_code) == "429"


def _retry_after_seconds(error: BaseException) -> float | None:
    value = getattr(error, "retry_after_seconds", None)
    return value if isinstance(value, (int, float)) and value > 0 else None
