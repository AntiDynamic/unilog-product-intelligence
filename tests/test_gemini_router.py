"""Unit tests for GeminiRouter routing, fallback, and error handling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.providers.gemini import GeminiProviderError
from unilog_product_intelligence.providers.gemini_router import (
    GeminiRouter,
    NON_RETRYABLE_STATUS_CODES,
    RETRYABLE_STATUS_CODES,
    _is_model_specific_error,
    should_fallback,
)


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


def test_should_fallback_matrix() -> None:
    # Non-retryable
    for code in (400, 401, 403, 404, 422):
        err = RuntimeError(f"Error {code}")
        setattr(err, "status_code", code)
        assert should_fallback(err) is False
        assert _is_model_specific_error(err) is False

    # Retryable
    for code in (408, 429, 500, 502, 503, 504):
        err = RuntimeError(f"Error {code}")
        setattr(err, "status_code", code)
        assert should_fallback(err) is True
        assert _is_model_specific_error(err) is True

    # Provider codes
    for pcode in ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED"):
        err = RuntimeError(f"Error: {pcode}")
        setattr(err, "provider_code", pcode)
        assert should_fallback(err) is True
