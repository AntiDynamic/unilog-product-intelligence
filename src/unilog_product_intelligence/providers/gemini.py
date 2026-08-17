"""Bounded Gemini Interactions adapter for structured and retrieval-assisted tasks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
        self.retry_after_seconds = _retry_after_seconds(error)
        self.request_id = getattr(error, "request_id", None)
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
        telemetry = _extract_tool_telemetry(getattr(response, "steps", None) or [])
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
            tool_calls=telemetry.search_call_count + telemetry.url_context_call_count,
            tool_use_input_tokens=_usage(usage, "tool_use_input_tokens"),
            search_call_count=telemetry.search_call_count,
            search_result_count=telemetry.search_result_count,
            search_queries=telemetry.search_queries,
            search_result_urls=telemetry.search_result_urls,
            search_suggestions=telemetry.search_suggestions,
            url_context_call_count=telemetry.url_context_call_count,
            url_context_result_count=telemetry.url_context_result_count,
            url_context_urls=telemetry.url_context_urls,
        )


@dataclass(frozen=True)
class _ToolTelemetry:
    search_call_count: int = 0
    search_result_count: int = 0
    search_queries: tuple[str, ...] = ()
    search_result_urls: tuple[str, ...] = ()
    search_suggestions: tuple[str, ...] = ()
    url_context_call_count: int = 0
    url_context_result_count: int = 0
    url_context_urls: tuple[str, ...] = ()


def _extract_tool_telemetry(steps: Any) -> _ToolTelemetry:
    search_queries: list[str] = []
    search_result_urls: list[str] = []
    search_suggestions: list[str] = []
    url_context_urls: list[str] = []
    search_call_count = 0
    search_result_count = 0
    url_context_call_count = 0
    url_context_result_count = 0

    for step in steps:
        step_type = str(getattr(step, "type", "")).casefold()
        if step_type == "google_search_call":
            search_call_count += 1
            arguments = getattr(step, "arguments", None)
            _append_unique(search_queries, _strings(getattr(arguments, "queries", None)))
        elif step_type == "google_search_result":
            results = _as_list(getattr(step, "result", None))
            search_result_count += len(results)
            for result in results:
                _collect_urls(result, search_result_urls)
                _append_unique(
                    search_suggestions, _strings(getattr(result, "search_suggestions", None))
                )
        elif step_type == "url_context_call":
            url_context_call_count += 1
            arguments = getattr(step, "arguments", None)
            _append_unique(url_context_urls, _strings(getattr(arguments, "urls", None)))
        elif step_type == "url_context_result":
            results = _as_list(getattr(step, "result", None))
            url_context_result_count += len(results)
            for result in results:
                _collect_urls(result, url_context_urls)

    return _ToolTelemetry(
        search_call_count=search_call_count,
        search_result_count=search_result_count,
        search_queries=tuple(search_queries),
        search_result_urls=tuple(search_result_urls),
        search_suggestions=tuple(search_suggestions),
        url_context_call_count=url_context_call_count,
        url_context_result_count=url_context_result_count,
        url_context_urls=tuple(url_context_urls),
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def _append_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _collect_urls(value: Any, target: list[str]) -> None:
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            _append_unique(target, [value])
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _collect_urls(item, target)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_urls(item, target)
        return
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        _collect_urls(model_dump(), target)
        return
    direct_url = getattr(value, "url", None) or getattr(value, "uri", None)
    if isinstance(direct_url, str):
        _collect_urls(direct_url, target)
        return
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping) and attributes:
        _collect_urls(attributes, target)


def _retry_after_seconds(error: Exception) -> float | None:
    value = getattr(error, "retry_after_seconds", None)
    return value if isinstance(value, (int, float)) and value > 0 else None


def _usage(usage: Any, name: str) -> int | None:
    value = getattr(usage, name, None) if usage else None
    return value if isinstance(value, int) else None
