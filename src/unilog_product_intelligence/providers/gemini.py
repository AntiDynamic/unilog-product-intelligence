"""Bounded Gemini Interactions adapter for structured and retrieval-assisted tasks."""

from time import monotonic
from typing import Any

from google.genai import Client
from google.genai.interactions import TextResponseFormat

from unilog_product_intelligence.config import Settings

from .base import LLMProvider, LLMRequest, LLMResponse


class GeminiConfigurationError(RuntimeError):
    """Raised when the provider has no API key configured."""


class GeminiProviderError(RuntimeError):
    """Sanitized Gemini SDK failure with non-secret provider metadata."""

    def __init__(self, error: Exception) -> None:
        self.status_code = getattr(error, "status_code", None)
        self.provider_code = getattr(error, "code", None)
        self.error_type = type(error).__name__
        self.provider_message = str(error)[:300]
        super().__init__(
            f"Gemini request failed status={self.status_code or 'unknown'} "
            f"code={self.provider_code or 'unknown'} type={self.error_type} "
            f"message={self.provider_message}"
        )


class GeminiProvider(LLMProvider):
    """Uses current Interactions structured output and explicit built-in tools."""

    def __init__(self, settings: Settings, client: Any | None = None, max_retries: int = 0) -> None:
        self.model = settings.gemini_model
        self._api_key = settings.gemini_api_key
        self._client = client
        self._max_retries = max_retries
        self._live_external_execution = settings.live_external_execution

    @property
    def api_key_configured(self) -> bool:
        return self._api_key is not None

    def generate(self, request: LLMRequest) -> LLMResponse:
        return self._generate(request, None)

    def generate_with_tools(self, request: LLMRequest, tools: list[dict[str, Any]]) -> LLMResponse:
        allowed = {"google_search", "url_context"}
        if any(tool.get("type") not in allowed for tool in tools):
            raise ValueError("Only explicitly supported retrieval tools may be enabled")
        return self._generate(request, tools)

    def _generate(self, request: LLMRequest, tools: list[dict[str, Any]] | None) -> LLMResponse:
        if not self.api_key_configured:
            raise GeminiConfigurationError("GEMINI_API_KEY is required for Gemini execution")
        if self._api_key is None:
            raise GeminiConfigurationError("GEMINI_API_KEY is required for Gemini execution")
        if self._client is None and not self._live_external_execution:
            raise GeminiConfigurationError(
                "LIVE_EXTERNAL_EXECUTION=true is required for live Gemini calls"
            )
        client = self._client or Client(api_key=self._api_key.get_secret_value())
        started = monotonic()
        try:
            arguments: dict[str, Any] = {"model": self.model, "input": request.input_text}
            if request.response_schema is not None:
                arguments["response_format"] = [
                    TextResponseFormat(
                        mime_type="application/json", schema_=request.response_schema
                    )
                ]
            if tools:
                arguments["tools"] = tools
            response = client.interactions.create(**arguments)
        except Exception as error:
            raise GeminiProviderError(error) from error
        usage = getattr(response, "usage_metadata", None) or getattr(response, "usage", None)
        tool_calls = sum(
            1
            for step in (getattr(response, "steps", None) or [])
            if "tool" in str(getattr(step, "type", "")).casefold()
        )
        return LLMResponse(
            output_text=str(getattr(response, "output_text", "")),
            model=self.model,
            input_tokens=_usage(usage, "prompt_token_count") or _usage(usage, "input_tokens"),
            output_tokens=_usage(usage, "candidates_token_count") or _usage(usage, "output_tokens"),
            cached_tokens=_usage(usage, "cached_content_token_count"),
            total_tokens=_usage(usage, "total_token_count"),
            latency_ms=round((monotonic() - started) * 1000),
            request_id=getattr(response, "id", None),
            retry_count=0,
            tool_calls=tool_calls,
            tool_use_input_tokens=_usage(usage, "tool_use_input_tokens"),
        )


def _usage(usage: Any, name: str) -> int | None:
    value = getattr(usage, name, None) if usage else None
    return value if isinstance(value, int) else None
