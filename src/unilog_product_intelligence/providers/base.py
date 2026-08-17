"""Provider-neutral LLM provider port and observable request envelopes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMRequest:
    task: str
    input_text: str
    response_schema: dict[str, Any] | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class LLMResponse:
    output_text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    latency_ms: int | None = None
    tool_calls: int = 0
    request_id: str | None = None
    total_tokens: int | None = None
    retry_count: int = 0
    estimated_cost_usd: float | None = None
    tool_use_input_tokens: int | None = None
    search_call_count: int = 0
    search_result_count: int = 0
    search_queries: tuple[str, ...] = ()
    search_result_urls: tuple[str, ...] = ()
    search_suggestions: tuple[str, ...] = ()
    url_context_call_count: int = 0
    url_context_result_count: int = 0
    url_context_urls: tuple[str, ...] = ()


class LLMProvider(ABC):
    """Provider boundary; domain/application code never receives SDK objects."""

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a validated provider response."""
