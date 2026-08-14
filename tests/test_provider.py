import pytest

from unilog_product_intelligence.config import Settings
from unilog_product_intelligence.providers import GeminiProvider, LLMRequest, LocalProvider
from unilog_product_intelligence.providers.gemini import GeminiConfigurationError


def test_gemini_provider_requires_key_before_network_execution() -> None:
    provider = GeminiProvider(Settings(_env_file=None))

    with pytest.raises(GeminiConfigurationError, match="GEMINI_API_KEY"):
        provider.generate(LLMRequest(task="test", input_text="no network call"))


def test_local_provider_is_an_explicit_future_slot() -> None:
    with pytest.raises(NotImplementedError, match="future phase"):
        LocalProvider().generate(LLMRequest(task="test", input_text="reserved"))
