"""Gemini adapter boundary.

No network call is made in Phase 0. The official ``google-genai`` dependency and model
contract are recorded so Phase 4 can add a real, bounded, observable implementation.
"""

from google.genai import Client

from unilog_product_intelligence.config import GEMINI_MODEL, Settings

from .base import LLMProvider, LLMRequest, LLMResponse


class GeminiProvider(LLMProvider):
    """Configuration-only Gemini provider placeholder for Phase 0."""

    def __init__(self, settings: Settings) -> None:
        self.model = settings.gemini_model
        self._api_key_configured = settings.gemini_api_key is not None
        self._client_type = Client

    @property
    def api_key_configured(self) -> bool:
        """Whether a key is configured, without exposing its value."""

        return self._api_key_configured

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Reject calls until the Phase 4 integration is deliberately implemented."""

        del request
        raise NotImplementedError(
            f"Gemini calls are intentionally disabled in Phase 0 for model {GEMINI_MODEL}."
        )
