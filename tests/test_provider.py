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


class _Interactions:
    def __init__(self) -> None:
        self.arguments: dict[str, object] | None = None

    def create(self, **kwargs: object) -> object:
        self.arguments = kwargs
        return type("Response", (), {"output_text": "{}", "id": "request-1"})()


class _Client:
    def __init__(self) -> None:
        self.interactions = _Interactions()


def test_gemini_provider_forwards_structured_response_format() -> None:
    client = _Client()
    provider = GeminiProvider(Settings(_env_file=None, gemini_api_key="test"), client=client)
    provider.generate(LLMRequest(task="test", input_text="x", response_schema={"type": "object"}))
    assert client.interactions.arguments is not None
    assert isinstance(client.interactions.arguments["response_format"], list)


def test_gemini_provider_extracts_search_and_url_context_steps() -> None:
    class TelemetryInteractions:
        def create(self, **kwargs: object) -> object:
            return type(
                "Response",
                (),
                {
                    "output_text": "{}",
                    "id": "request-telemetry",
                    "steps": [
                        type(
                            "Step",
                            (),
                            {
                                "type": "google_search_call",
                                "arguments": type("Arguments", (), {"queries": ["Acme ABC123"]})(),
                            },
                        )(),
                        type(
                            "Step",
                            (),
                            {
                                "type": "google_search_result",
                                "result": [
                                    type(
                                        "Result",
                                        (),
                                        {
                                            "url": "https://acme.example/ABC123",
                                            "search_suggestions": "Acme official",
                                        },
                                    )()
                                ],
                            },
                        )(),
                        type(
                            "Step",
                            (),
                            {
                                "type": "url_context_call",
                                "arguments": type(
                                    "Arguments", (), {"urls": ["https://acme.example/ABC123"]}
                                )(),
                            },
                        )(),
                        type(
                            "Step",
                            (),
                            {
                                "type": "url_context_result",
                                "result": [
                                    type(
                                        "Result",
                                        (),
                                        {"url": "https://acme.example/ABC123"},
                                    )()
                                ],
                            },
                        )(),
                    ],
                },
            )()

    client = type("Client", (), {"interactions": TelemetryInteractions()})()
    provider = GeminiProvider(Settings(_env_file=None, gemini_api_key="test"), client=client)
    response = provider.generate_with_tools(
        LLMRequest(task="test", input_text="x"),
        [{"type": "google_search"}, {"type": "url_context"}],
    )

    assert response.search_call_count == 1
    assert response.search_result_count == 1
    assert response.search_queries == ("Acme ABC123",)
    assert response.search_result_urls == ("https://acme.example/ABC123",)
    assert response.search_suggestions == ("Acme official",)
    assert response.url_context_call_count == 1
    assert response.url_context_result_count == 1
    assert response.url_context_urls == ("https://acme.example/ABC123",)
