"""Bounded retrieval agents: discovery may suggest, application policy decides."""

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest

from .core import DomainCandidate, DomainResolver, SourceDecision


class DiscoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[DomainCandidate] = Field(default_factory=list)
    unresolved_reason: str | None = None


class ManufacturerDiscoveryAgent:
    """Uses Search only when deterministic domain sources are exhausted."""

    def __init__(self, provider: LLMProvider, resolver: DomainResolver) -> None:
        self.provider = provider
        self.resolver = resolver

    def discover(
        self,
        manufacturer_id: str,
        manufacturer_name: str,
        mpn: str | None = None,
        family: str | None = None,
        description: str | None = None,
    ) -> DiscoveryResult:
        deterministic = self.resolver.resolve(manufacturer_id, manufacturer_name)
        if deterministic:
            return DiscoveryResult(candidates=list(deterministic))
        queries = self.resolver.discovery_queries(manufacturer_name, mpn, family, description)
        prompt = _prompt() + "\nQUERIES (discovery data):\n" + "\n".join(queries)
        request = LLMRequest(
            task="manufacturer_discovery",
            input_text=prompt,
            response_schema=DiscoveryResult.model_json_schema(),
        )
        generate_with_tools = getattr(self.provider, "generate_with_tools", None)
        response = (
            generate_with_tools(request, [{"type": "google_search"}])
            if callable(generate_with_tools)
            else self.provider.generate(request)
        )
        result = DiscoveryResult.model_validate_json(response.output_text)
        return DiscoveryResult(
            candidates=[
                candidate.model_copy(
                    update={"status": SourceDecision.CANDIDATE_MANUFACTURER_SOURCE}
                )
                for candidate in result.candidates
            ],
            unresolved_reason=result.unresolved_reason,
        )


def _prompt() -> str:
    return (
        "ROLE: Manufacturer domain discovery. Search is candidate discovery only. Prefer official "
        "manufacturer domains; reject distributors and marketplaces. Never claim domain ownership "
        "or fabricate URLs. The application verifier is authoritative. Return concise "
        "structured JSON only."
    )
