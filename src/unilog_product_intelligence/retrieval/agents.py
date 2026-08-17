"""Bounded retrieval agents: discovery may suggest, application policy decides."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.application.scale import FailureCategory, classify_429
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse

from .core import DomainCandidate, DomainResolver, Phase5FailureReason, SourceDecision
from .source_discovery import DeterministicUrlStrategy, _strategy_names_for


class DiscoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[DomainCandidate] = Field(default_factory=list)
    unresolved_reason: str | None = None
    queries: tuple[str, ...] = ()
    search_requested: bool = False
    search_tool_calls: int = 0
    search_result_count: int = 0
    search_result_urls: tuple[str, ...] = ()
    search_suggestions: tuple[str, ...] = ()
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    latency_ms: int | None = None
    request_id: str | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    # Observability: explicit failure classification and strategy audit trail
    failure_reason: Phase5FailureReason | None = None
    retrieval_strategies_attempted: tuple[str, ...] = ()
    deterministic_candidates_tried: int = 0


class ManufacturerDiscoveryAgent:
    """Uses deterministic domain strategies first; Gemini Search only as final fallback.

    Retrieval priority:
      1. Verified domain cache (DomainResolver.resolve returns VERIFIED)
      2. Registered ManufacturerProfile verified domains
      3. Audited manufacturer domain catalog (by name or brand alias)
      4. Deterministic URL candidates from DeterministicUrlStrategy
      5. Gemini Search (fallback only when all deterministic paths are exhausted)

    A 429 or billing failure from Gemini is recorded honestly in failure_reason;
    the deterministic result (if any) is still returned.
    """

    def __init__(
        self,
        provider: LLMProvider,
        resolver: DomainResolver,
        url_strategy: DeterministicUrlStrategy | None = None,
    ) -> None:
        self.provider = provider
        self.resolver = resolver
        self._url_strategy = url_strategy or DeterministicUrlStrategy()

    def discover(
        self,
        manufacturer_id: str,
        manufacturer_name: str,
        mpn: str | None = None,
        family: str | None = None,
        description: str | None = None,
        brand: str | None = None,
    ) -> DiscoveryResult:
        """Discover manufacturer domains for the product.

        Parameters
        ----------
        manufacturer_id:
            Stable identifier for this manufacturer (used for cache keying).
        manufacturer_name:
            Raw manufacturer name from the input row (Part_Manuf).
        mpn:
            Manufacturer part number — used for deterministic URL generation.
        family:
            Product family hint used for Gemini discovery queries only.
        description:
            Product description hint used for Gemini discovery queries only.
        brand:
            Brand hint (Unilog_Brand / E1_Brand / DIB_Brand).  Enables brand-alias
            lookup in the domain catalog when Part_Manuf is a distributor.
        """
        strategies: list[str] = []

        # ── Step 1: Deterministic domain resolution ───────────────────────────
        strategies.append("domain_resolver")
        deterministic = self.resolver.resolve(
            manufacturer_id, manufacturer_name, brand=brand
        )
        verified = tuple(
            c for c in deterministic if c.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
        )
        if verified:
            # Fast path: already have verified domains — no Gemini needed.
            verified_domains = tuple(c.domain for c in verified)
            det_strategies = _strategy_names_for(verified_domains, mpn)
            strategies.extend(det_strategies)
            det_urls = self._url_strategy.all_candidates(verified_domains, mpn)
            return DiscoveryResult(
                candidates=list(verified),
                search_result_urls=det_urls,
                retrieval_strategies_attempted=tuple(strategies),
                deterministic_candidates_tried=len(det_urls) if det_urls else len(verified),
            )

        # ── Step 2: Deterministic URL candidates for candidate domains ────────
        candidate_domains = tuple(c.domain for c in deterministic)
        if candidate_domains:
            strategies.append("deterministic_url_patterns")
            det_urls = self._url_strategy.all_candidates(candidate_domains, mpn)
            if det_urls:
                return DiscoveryResult(
                    candidates=list(deterministic),
                    search_result_urls=det_urls,
                    retrieval_strategies_attempted=tuple(strategies),
                    deterministic_candidates_tried=len(det_urls),
                )

        # ── Step 3: Gemini Search fallback ────────────────────────────────────
        strategies.append("gemini_search_fallback")
        queries = self.resolver.discovery_queries(manufacturer_name, mpn, family, description)
        prompt = _prompt() + "\nQUERIES (discovery data):\n" + "\n".join(queries)
        request = LLMRequest(
            task="manufacturer_discovery",
            input_text=prompt,
            response_schema=DiscoveryResult.model_json_schema(),
        )
        generate_with_tools = cast(
            Callable[[LLMRequest, list[dict[str, object]]], LLMResponse] | None,
            getattr(self.provider, "generate_with_tools", None),
        )
        search_requested = generate_with_tools is not None
        failure_reason: Phase5FailureReason | None = None
        try:
            if generate_with_tools is not None:
                response = generate_with_tools(request, [{"type": "google_search"}])
            else:
                response = self.provider.generate(request)
        except Exception as exc:
            # Classify the failure explicitly rather than collapsing to a generic error.
            failure_reason = _classify_gemini_failure(exc)
            return DiscoveryResult(
                candidates=list(deterministic),
                unresolved_reason=f"gemini_error:{type(exc).__name__}",
                queries=queries,
                search_requested=search_requested,
                search_tool_calls=0,
                search_result_count=0,
                failure_reason=failure_reason,
                retrieval_strategies_attempted=tuple(strategies),
                deterministic_candidates_tried=len(deterministic),
            )

        result = DiscoveryResult.model_validate_json(response.output_text)
        seen = {c.domain.casefold() for c in deterministic}
        candidates = list(deterministic)
        candidates.extend(c for c in result.candidates if c.domain.casefold() not in seen)
        return DiscoveryResult(
            candidates=[
                c.model_copy(update={"status": SourceDecision.CANDIDATE_MANUFACTURER_SOURCE})
                for c in candidates
            ],
            unresolved_reason=result.unresolved_reason,
            queries=tuple(dict.fromkeys((*queries, *response.search_queries))),
            search_requested=search_requested,
            search_tool_calls=response.search_call_count if search_requested else 0,
            search_result_count=response.search_result_count if search_requested else 0,
            search_result_urls=response.search_result_urls if search_requested else (),
            search_suggestions=response.search_suggestions if search_requested else (),
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cached_tokens=response.cached_tokens,
            latency_ms=response.latency_ms,
            request_id=response.request_id,
            total_tokens=response.total_tokens,
            estimated_cost_usd=response.estimated_cost_usd,
            failure_reason=failure_reason,
            retrieval_strategies_attempted=tuple(strategies),
            deterministic_candidates_tried=len(deterministic),
        )


def _classify_gemini_failure(exc: BaseException) -> Phase5FailureReason:
    """Map a Gemini exception to a granular Phase5FailureReason."""
    category = classify_429(exc)
    if category in {FailureCategory.RATE_LIMIT, FailureCategory.UNKNOWN_429}:
        return Phase5FailureReason.GEMINI_RATE_LIMIT
    if category in {FailureCategory.SPEND_LIMIT, FailureCategory.PROJECT_QUOTA}:
        return Phase5FailureReason.GEMINI_BILLING_FAILURE
    status_code = getattr(exc, "status_code", None)
    if status_code in {401, 403}:
        return Phase5FailureReason.GEMINI_BILLING_FAILURE
    err_str = str(exc).casefold()
    if "billing" in err_str or "quota" in err_str or "auth" in err_str:
        return Phase5FailureReason.GEMINI_BILLING_FAILURE
    return Phase5FailureReason.RETRIEVAL_REQUIRES_REVIEW


def _prompt() -> str:
    return (
        "ROLE: Manufacturer domain discovery. Search is candidate discovery only. Prefer official "
        "manufacturer domains; reject distributors and marketplaces. Never claim domain ownership "
        "or fabricate URLs. The application verifier is authoritative. Return concise "
        "structured JSON only."
    )
