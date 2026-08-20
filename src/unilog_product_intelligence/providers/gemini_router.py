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


def _is_model_specific_error(error: Exception) -> bool:
    """Return True for errors where a fallback model might succeed.

    Fail-fast errors (auth, billing/spend limits) return False.
    Rate limits (429), model not found (404), and transient server errors (5xx) return True.
    """
    status_code = getattr(error, "status_code", None)
    if status_code in {401, 403}:
        # Auth failure — never route to fallback (same credentials will fail)
        return False

    normalized_status = int(status_code) if str(status_code).isdigit() else None

    if normalized_status == 429:
        category = classify_429(error)
        if category == FailureCategory.SPEND_LIMIT:
            # Spend limit reached — fail fast immediately
            return False
        # RATE_LIMIT, PROJECT_QUOTA, CAPACITY, SEARCH_LIMIT can fallback
        return True

    if normalized_status in {404, 408, 500, 502, 503, 504}:
        return True

    provider_code = getattr(error, "provider_code", None)
    if provider_code in {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED"}:
        return True

    return False


class GeminiRouter(LLMProvider):
    """Routes LLM requests to primary, fallback, or escalation models.

    Preserves the LLMProvider port contract so downstream services (orchestrator,
    discovery agent, enrichment agent) require no code changes.

    Routing Policy:
      - Primary call fails with 429 (rate/quota), 404 (model unavailable), or 5xx
        → seamlessly falls back to the configured fallback provider.
      - 401/403 (auth) and spend limits fail fast without masked fallbacks.
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
            if self.fallback is not None and _is_model_specific_error(error):
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
            if self.fallback is not None and _is_model_specific_error(error):
                if hasattr(self.fallback, "generate_with_tools"):
                    return self.fallback.generate_with_tools(request, tools)
                return self.fallback.generate(request)
            raise

    def generate_with_strong_model(self, request: LLMRequest) -> LLMResponse:
        """Route to the escalation model for conflict resolution."""
        target = self.strong_model or self.primary
        return target.generate(request)


__all__ = ["GeminiRouter", "_is_model_specific_error"]
