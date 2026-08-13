"""Future local-model provider placeholder."""

from .base import LLMProvider, LLMRequest, LLMResponse


class LocalProvider(LLMProvider):
    """Reserved adapter slot; local-model research is out of scope for Phase 0."""

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Reject calls until a future provider decision is recorded."""

        del request
        raise NotImplementedError("LocalProvider is reserved for a future phase.")
