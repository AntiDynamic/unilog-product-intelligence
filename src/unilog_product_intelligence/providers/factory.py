"""Provider factory and execution mode definitions for UNILOG."""

from __future__ import annotations

from enum import StrEnum

from unilog_product_intelligence.config import Settings, get_settings
from unilog_product_intelligence.providers.base import LLMProvider
from unilog_product_intelligence.providers.gemini import (
    GeminiConfigurationError,
    GeminiProvider,
)


class ExecutionMode(StrEnum):
    """Explicit pipeline execution mode."""

    LIVE_DETERMINISTIC = "LIVE_DETERMINISTIC"
    LIVE_GEMINI = "LIVE_GEMINI"

    @classmethod
    def from_str(cls, value: str) -> ExecutionMode:
        """Parse string or CLI argument into validated ExecutionMode."""
        normalized = value.strip().upper().replace("-", "_")
        if normalized in {"LIVE_DETERMINISTIC", "DETERMINISTIC"}:
            return cls.LIVE_DETERMINISTIC
        if normalized in {"LIVE_GEMINI", "GEMINI"}:
            return cls.LIVE_GEMINI
        raise ValueError(
            f"Unknown execution mode: '{value}'. Expected 'live-deterministic' or 'live-gemini'."
        )


def build_provider(
    mode: ExecutionMode | str,
    settings: Settings | None = None,
) -> LLMProvider:
    """Build and return the appropriate LLMProvider for the requested execution mode.

    Fail-closed guarantees:
      - LIVE_DETERMINISTIC: Returns DeterministicEvaluationProvider (zero Gemini cost / API calls).
      - LIVE_GEMINI: Returns real GeminiProvider. If GEMINI_API_KEY is not configured or
        provider configuration is invalid, raises GeminiConfigurationError immediately.
        Never silently falls back to DeterministicEvaluationProvider.
    """
    exec_mode = ExecutionMode.from_str(mode) if isinstance(mode, str) else mode

    if exec_mode == ExecutionMode.LIVE_DETERMINISTIC:
        from unilog_product_intelligence.application.evaluation import (
            DeterministicEvaluationProvider,
        )

        return DeterministicEvaluationProvider()

    if exec_mode == ExecutionMode.LIVE_GEMINI:
        cfg = settings or get_settings()
        if not cfg.gemini_api_key or not cfg.gemini_api_key.get_secret_value().strip():
            raise GeminiConfigurationError(
                "GEMINI_API_KEY is required for LIVE_GEMINI execution mode, "
                "but none was configured."
            )
        # Enable live external execution if API key is supplied
        if not cfg.live_external_execution:
            cfg = cfg.model_copy(update={"live_external_execution": True})
        return GeminiProvider(settings=cfg)

    raise ValueError(f"Unsupported execution mode: {exec_mode}")
