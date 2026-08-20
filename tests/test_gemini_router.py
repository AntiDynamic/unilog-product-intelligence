"""Unit tests for GeminiRouter routing, fallback, and error handling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.providers.gemini import GeminiProviderError
from unilog_product_intelligence.providers.gemini_router import GeminiRouter, _is_model_specific_error


class MockLLMProvider(LLMProvider):
    def __init__(self, name: str = "mock-primary") -> None:
        self.model = name
        self.call_count = 0
        self.should_fail: Exception | None = None
        self.response_text = "mock output"

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        if self.should_fail is not None:
            raise self.should_fail
        return LLMResponse(output_text=self.response_text, model=self.model)

    def generate_with_tools(self, request: LLMRequest, tools: list[dict]) -> LLMResponse:
        self.call_count += 1
        if self.should_fail is not None:
            raise self.should_fail
        return LLMResponse(output_text=self.response_text, model=self.model)


def test_gemini_router_primary_success() -> None:
    primary = MockLLMProvider("gemini-2.5-flash")
    fallback = MockLLMProvider("gemini-2.0-flash")
    router = GeminiRouter(primary=primary, fallback=fallback)

    req = LLMRequest(task="test", input_text="hello")
    resp = router.generate(req)

    assert resp.output_text == "mock output"
    assert resp.model == "gemini-2.5-flash"
    assert primary.call_count == 1
    assert fallback.call_count == 0


def test_gemini_router_fallback_on_429() -> None:
    primary = MockLLMProvider("gemini-2.5-flash")
    fallback = MockLLMProvider("gemini-2.0-flash")
    fallback.response_text = "fallback output"

    # Simulate 429 rate limit
    err = RuntimeError("429 RESOURCE_EXHAUSTED: Rate limit exceeded")
    setattr(err, "status_code", 429)
    setattr(err, "code", "RESOURCE_EXHAUSTED")
    primary.should_fail = err

    router = GeminiRouter(primary=primary, fallback=fallback)
    req = LLMRequest(task="test", input_text="hello")
    resp = router.generate(req)

    assert resp.output_text == "fallback output"
    assert resp.model == "gemini-2.0-flash"
    assert primary.call_count == 1
    assert fallback.call_count == 1


def test_gemini_router_fail_fast_on_auth_401() -> None:
    primary = MockLLMProvider("gemini-2.5-flash")
    fallback = MockLLMProvider("gemini-2.0-flash")

    err = RuntimeError("401 Unauthorized")
    setattr(err, "status_code", 401)
    primary.should_fail = err

    router = GeminiRouter(primary=primary, fallback=fallback)
    req = LLMRequest(task="test", input_text="hello")

    with pytest.raises(RuntimeError) as exc_info:
        router.generate(req)

    assert "401" in str(exc_info.value)
    assert primary.call_count == 1
    assert fallback.call_count == 0


def test_gemini_router_generate_with_strong_model() -> None:
    primary = MockLLMProvider("gemini-2.5-flash")
    strong = MockLLMProvider("gemini-2.5-pro")
    strong.response_text = "reasoned output"

    router = GeminiRouter(primary=primary, strong_model=strong)
    req = LLMRequest(task="conflict_resolution", input_text="resolve 120V vs 125V")
    resp = router.generate_with_strong_model(req)

    assert resp.output_text == "reasoned output"
    assert resp.model == "gemini-2.5-pro"
    assert strong.call_count == 1
    assert primary.call_count == 0


def test_is_model_specific_error_classification() -> None:
    e429 = RuntimeError("429")
    setattr(e429, "status_code", 429)
    assert _is_model_specific_error(e429) is True

    e404 = RuntimeError("404")
    setattr(e404, "status_code", 404)
    assert _is_model_specific_error(e404) is True

    e503 = RuntimeError("503")
    setattr(e503, "status_code", 503)
    assert _is_model_specific_error(e503) is True

    e401 = RuntimeError("401")
    setattr(e401, "status_code", 401)
    assert _is_model_specific_error(e401) is False

    e403 = RuntimeError("403")
    setattr(e403, "status_code", 403)
    assert _is_model_specific_error(e403) is False
