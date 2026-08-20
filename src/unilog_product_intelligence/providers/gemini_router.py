"""Routing and fallback provider wrapping primary, fallback, and escalation LLM providers."""

from __future__ import annotations

from typing import Any

from unilog_product_intelligence.application.scale import FailureCategory, classify_429
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse
from unilog_product_intelligence.providers.gemini import (
    GeminiConcurrencyLimiter,
    GeminiConfigurationError,
    GeminiProviderError,
)

# Explicit status code matrix for routing decisions
NON_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({400, 401, 403, 404, 422})
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})
RETRYABLE_PROVIDER_CODES: frozenset[str] = frozenset({
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
    "DEADLINE_EXCEEDED",
    "INTERNAL",
})


def should_fallback(error: Exception) -> bool:
    """Return True if an error is transient/recoverable via a fallback model.

    Fail-fast errors (auth, bad request, unprocessable entity, spend limit) return False.
    Rate limits (429), timeouts (408), and transient server errors (5xx) return True.
    """
    status_code = getattr(error, "status_code", None)
    normalized_status = int(status_code) if str(status_code).isdigit() else None

    # Check error message if status_code is not directly on exception
    if normalized_status is None:
        err_msg = str(error)
        for code in NON_RETRYABLE_STATUS_CODES:
            if f"{code}" in err_msg and ("status" in err_msg.casefold() or "error" in err_msg.casefold() or f" {code} " in f" {err_msg} "):
                normalized_status = code
                break
        if normalized_status is None:
            for code in RETRYABLE_STATUS_CODES:
                if f"{code}" in err_msg and ("status" in err_msg.casefold() or "error" in err_msg.casefold() or f" {code} " in f" {err_msg} "):
                    normalized_status = code
                    break

    if normalized_status in NON_RETRYABLE_STATUS_CODES:
        return False

    if normalized_status == 429:
        category = classify_429(error)
        if category == FailureCategory.SPEND_LIMIT:
            # Spend limit reached — fail fast immediately
            return False
        # RATE_LIMIT, PROJECT_QUOTA, CAPACITY, SEARCH_LIMIT can fallback
        return True

    if normalized_status in RETRYABLE_STATUS_CODES:
        return True

    provider_code = getattr(error, "provider_code", None) or getattr(error, "code", None)
    if provider_code and str(provider_code).upper() in RETRYABLE_PROVIDER_CODES:
        return True

    err_str = str(error).upper()
    if any(code in err_str for code in RETRYABLE_PROVIDER_CODES):
        return True

    return False


# Backward-compatibility alias
_is_model_specific_error = should_fallback


class GeminiRouter(LLMProvider):
    """Routes LLM requests to primary, fallback, or escalation models.

    Preserves the LLMProvider port contract so downstream services (orchestrator,
    discovery agent, enrichment agent) require no code changes.

    Routing Policy:
      - Primary call fails with 429 (rate/quota), 408 (timeout), or 5xx
        → seamlessly falls back to the configured fallback provider.
      - 400, 401, 403, 404, 422, and spend limits fail fast without masked fallbacks.
      - Conflict escalation: generate_with_strong_model() routes specifically to
        a higher-reasoning model (e.g. Gemini Pro).
    """

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider | None = None,
        strong_model: LLMProvider | None = None,
        limiter: GeminiConcurrencyLimiter | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.strong_model = strong_model
        self.limiter = limiter

    @property
    def supports_unified_pre_enrichment(self) -> bool:
        return bool(getattr(self.primary, "supports_unified_pre_enrichment", True))

    @property
    def supports_live_web_search(self) -> bool:
        return bool(getattr(self.primary, "supports_live_web_search", True))

    @property
    def model(self) -> str:
        return str(getattr(self.primary, "model", "gemini-router"))

    def generate(self, request: LLMRequest) -> LLMResponse:
        try:
            return self.primary.generate(request)
        except Exception as error:
            if self.fallback is not None and should_fallback(error):
                return self.fallback.generate(request)
            raise

    def generate_with_tools(
        self, request: LLMRequest, tools: list[dict[str, Any]]
    ) -> LLMResponse:
        try:
            if hasattr(self.primary, "generate_with_tools"):
                return self.primary.generate_with_tools(request, tools)
            return self.primary.generate(request)
        except Exception as error:
            if self.fallback is not None and should_fallback(error):
                if hasattr(self.fallback, "generate_with_tools"):
                    return self.fallback.generate_with_tools(request, tools)
                return self.fallback.generate(request)
            raise

    def generate_with_strong_model(self, request: LLMRequest) -> LLMResponse:
        """Route to the escalation model for conflict resolution."""
        target = self.strong_model or self.primary
        return target.generate(request)


__all__ = [
    "GeminiRouter",
    "NON_RETRYABLE_STATUS_CODES",
    "RETRYABLE_STATUS_CODES",
    "_is_model_specific_error",
    "should_fallback",
]
