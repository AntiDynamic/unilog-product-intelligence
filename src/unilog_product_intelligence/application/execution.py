"""Single controlled execution boundary for all Gemini provider calls."""

from __future__ import annotations

from typing import Any, cast

from unilog_product_intelligence.application.scale import QuotaCircuitBreaker, QuotaGuard, Usage
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
        guard = self.quota.check()
        if guard.decision.value != "ALLOW":
            raise RuntimeError(f"Gemini execution deferred: {guard.reason}")
        if tools is not None and callable(getattr(self.provider, "generate_with_tools", None)):
            response = cast(LLMResponse, self.provider.generate_with_tools(request, tools))  # type: ignore[attr-defined]
        else:
            response = self.provider.generate(request)
        self.quota.reserve(
            Usage(
                input_tokens=response.input_tokens or 0,
                output_tokens=response.output_tokens or 0,
                cached_tokens=response.cached_tokens or 0,
            )
        )
        self.breaker.record_success()
        return response
