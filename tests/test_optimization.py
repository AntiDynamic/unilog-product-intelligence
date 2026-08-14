from unilog_product_intelligence.application.optimization import (
    ManufacturerSearchCache,
    cost_scenarios,
    group_manufacturers,
)
from unilog_product_intelligence.application.scale import (
    EvidenceSelector,
    PromptCompressor,
    TokenBudget,
    estimate_context_tokens,
)


def test_token_budget_defers_large_context() -> None:
    result = TokenBudget(max_input_tokens=10).check(11, 1)
    assert result.reason == "TOKEN_BUDGET_DEFERRED_INPUT"


def test_evidence_selector_reduces_context() -> None:
    chunks = ["warranty section", "material: steel", "unrelated history"]
    assert EvidenceSelector().select(chunks, ["material"]) == ["material: steel"]


def test_prompt_compression_and_estimate() -> None:
    prompt = PromptCompressor().compress("extract", ["use evidence", "use evidence"], "steel")
    assert prompt.count("use evidence") == 1
    assert estimate_context_tokens(prompt) > 0


def test_negative_search_cache_and_grouping() -> None:
    cache = ManufacturerSearchCache()
    cache.put("Acme", "NO_OFFICIAL_DOMAIN_FOUND", None, "acme widget")
    assert cache.get("acme") is not None
    groups = group_manufacturers([{"Part_Manuf": "Acme"}, {"Part_Manuf": "acme"}])
    assert len(groups["acme"]) == 2


def test_cost_scenarios_are_labeled() -> None:
    scenarios = cost_scenarios(5)
    assert scenarios["deterministic_only"]["gemini_calls"] == 0
    assert scenarios["batch_50pct_model_discount"]["cost_usd"] is not None
