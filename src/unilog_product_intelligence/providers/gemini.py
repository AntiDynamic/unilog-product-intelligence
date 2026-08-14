"""Bounded Gemini Interactions adapter with no domain dependencies."""

from time import monotonic, sleep
from typing import Any

from google.genai import Client

from unilog_product_intelligence.config import Settings

from .base import LLMProvider, LLMRequest, LLMResponse


class GeminiConfigurationError(RuntimeError):
    """Raised when the provider has no API key configured."""


class GeminiProviderError(RuntimeError):
    """Sanitized Gemini SDK failure."""


class GeminiProvider(LLMProvider):
    """Uses the current Interactions primitive for strict JSON responses."""

    def __init__(self, settings: Settings, client: Any | None = None, max_retries: int = 2) -> None:
        self.model = settings.gemini_model
        self._api_key = settings.gemini_api_key
        self._client = client
        self._max_retries = max_retries

    @property
    def api_key_configured(self) -> bool:
        return self._api_key is not None

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key_configured:
            raise GeminiConfigurationError("GEMINI_API_KEY is required for Gemini execution")
        api_key = self._api_key
        if api_key is None:
            raise GeminiConfigurationError("GEMINI_API_KEY is required for Gemini execution")
        client = self._client or Client(api_key=api_key.get_secret_value())
        started = monotonic()
        for attempt in range(self._max_retries + 1):
            try:
                response = client.interactions.create(
                    model=self.model,
                    input=request.input_text,
                    response_format=_format(request.response_schema),
                )
                usage = getattr(response, "usage_metadata", None)
                return LLMResponse(
                    output_text=str(getattr(response, "output_text", "")),
                    model=self.model,
                    input_tokens=_usage(usage, "prompt_token_count"),
                    output_tokens=_usage(usage, "candidates_token_count"),
                    cached_tokens=_usage(usage, "cached_content_token_count"),
                    total_tokens=_usage(usage, "total_token_count"),
                    latency_ms=round((monotonic() - started) * 1000),
                    request_id=getattr(response, "id", None),
                    retry_count=attempt,
                )
            except Exception as error:
                if attempt == self._max_retries or not _transient(error):
                    raise GeminiProviderError("Gemini request failed") from error
                sleep(0.25 * 2**attempt)
        raise AssertionError("unreachable")


def _format(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    return (
        None
        if schema is None
        else {"type": "text", "mime_type": "application/json", "schema": schema}
    )


def _usage(usage: Any, name: str) -> int | None:
    value = getattr(usage, name, None) if usage else None
    return value if isinstance(value, int) else None


def _transient(error: Exception) -> bool:
    return getattr(error, "status_code", None) in {408, 429, 500, 502, 503, 504} or isinstance(
        error, TimeoutError
    )
