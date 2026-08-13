"""Provider-agnostic LLM port.

The application depends on this interface, not on a vendor SDK. Concrete providers are
adapters and must return validated, observable responses when implemented in a later phase.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMRequest:
    """Minimal provider-neutral request envelope."""

    task: str
    input_text: str
    response_schema: dict[str, Any] | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    """Provider-neutral response envelope with room for usage telemetry."""

    output_text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    latency_ms: int | None = None
    tool_calls: int = 0


class LLMProvider(ABC):
    """Dependency-inversion port for future structured model operations."""

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a provider response for a validated request."""
