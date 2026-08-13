import pytest

from unilog_product_intelligence.config import Settings
from unilog_product_intelligence.providers import GeminiProvider, LLMRequest, LocalProvider


def test_gemini_provider_does_not_call_network_in_phase_zero() -> None:
    provider = GeminiProvider(Settings(_env_file=None))

    with pytest.raises(NotImplementedError, match="disabled in Phase 0"):
        provider.generate(LLMRequest(task="test", input_text="no network call"))


def test_local_provider_is_an_explicit_future_slot() -> None:
    with pytest.raises(NotImplementedError, match="future phase"):
        LocalProvider().generate(LLMRequest(task="test", input_text="reserved"))
