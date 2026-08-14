"""Bounded Gemini Interactions adapter for structured and retrieval-assisted tasks."""

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
    """Uses current Interactions structured output and explicit built-in tools."""

    def __init__(self, settings: Settings, client: Any | None = None, max_retries: int = 2) -> None:
        self.model = settings.gemini_model
        self._api_key = settings.gemini_api_key
        self._client = client
        self._max_retries = max_retries

    @property
    def api_key_configured(self) -> bool:
        return self._api_key is not None

    def generate(self, request: LLMRequest) -> LLMResponse:
        return self._generate(request, None)

    def generate_with_tools(self, request: LLMRequest, tools: list[dict[str, Any]]) -> LLMResponse:
        """Use explicitly selected Google Search/URL Context tools only."""
        allowed = {"google_search", "url_context"}
        if any(tool.get("type") not in allowed for tool in tools):
            raise ValueError("Only explicitly supported retrieval tools may be enabled")
        return self._generate(request, tools)

    def _generate(self, request: LLMRequest, tools: list[dict[str, Any]] | None) -> LLMResponse:
        if not self.api_key_configured:
            raise GeminiConfigurationError("GEMINI_API_KEY is required for Gemini execution")
        api_key = self._api_key
        if api_key is None:
            raise GeminiConfigurationError("GEMINI_API_KEY is required for Gemini execution")
        client = self._client or Client(api_key=api_key.get_secret_value())
        started = monotonic()
        for attempt in range(self._max_retries + 1):
            try:
                arguments: dict[str, Any] = {
                    "model": self.model,
                    "input": request.input_text,
                    "response_format": _format(request.response_schema),
                }
                if tools:
                    arguments["tools"] = tools
                response = client.interactions.create(**arguments)
                usage = getattr(response, "usage_metadata", None) or getattr(
                    response, "usage", None
                )
                tool_calls = sum(
                    1
                    for step in (getattr(response, "steps", None) or [])
                    if "tool" in str(getattr(step, "type", "")).casefold()
                )
                return LLMResponse(
                    output_text=str(getattr(response, "output_text", "")),
                    model=self.model,
                    input_tokens=_usage(usage, "prompt_token_count")
                    or _usage(usage, "input_tokens"),
                    output_tokens=_usage(usage, "candidates_token_count")
                    or _usage(usage, "output_tokens"),
                    cached_tokens=_usage(usage, "cached_content_token_count"),
                    total_tokens=_usage(usage, "total_token_count"),
                    latency_ms=round((monotonic() - started) * 1000),
                    request_id=getattr(response, "id", None),
                    retry_count=attempt,
                    tool_calls=tool_calls,
                    tool_use_input_tokens=_usage(usage, "tool_use_input_tokens"),
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
