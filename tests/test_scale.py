import time

from unilog_product_intelligence.application.scale import (
    CostConfig,
    ExecutionMode,
    FailureCategory,
    GuardDecision,
    ModelExecutionRouter,
    QuotaCircuitBreaker,
    QuotaGuard,
    SafetyBudget,
    SearchBudget,
    TaskClass,
    Usage,
    classify_429,
    classify_task,
    estimate_batch,
    task_fingerprint,
)


def test_guard_distinguishes_local_budget() -> None:
    guard = QuotaGuard(SafetyBudget(max_daily_requests=1))
    assert guard.check().decision is GuardDecision.ALLOW
    guard.reserve(Usage(input_tokens=10))
    assert guard.check().decision is GuardDecision.BUDGET_DEFERRED


def test_search_budget_is_manufacturer_scoped() -> None:
    budget = SearchBudget(max_queries=2)
    assert budget.allow("Acme")
    budget.record("Acme")
    assert not budget.allow("acme")
    assert budget.allow("Other")


def test_routing_and_classification() -> None:
    router = ModelExecutionRouter()
    assert router.route(TaskClass.NON_AI) is ExecutionMode.DETERMINISTIC
    assert router.route(TaskClass.BATCHABLE, product_count=100) is ExecutionMode.BATCH
    assert router.route(TaskClass.INTERACTIVE, needs_tools=True) is ExecutionMode.INTERACTIONS
    assert classify_task("uom normalization") is TaskClass.NON_AI
    assert classify_task("manufacturer discovery") is TaskClass.EXTERNAL_DISCOVERY


def test_429_and_fingerprint_are_deterministic() -> None:
    assert classify_429(RuntimeError("too_many_requests quota")) is FailureCategory.PROJECT_QUOTA
    assert task_fingerprint("x", "y", "v1") == task_fingerprint("x", "y", "v1")


def test_cost_plan_is_explicitly_estimated() -> None:
    result = estimate_batch(5, cost=CostConfig(search_query_usd=1.0))
    assert result["estimated_gemini_calls"] == 5
    assert result["recommended_execution_mode"] == "BATCH"


def test_tpm_is_rolling_and_product_budget_is_enforced() -> None:
    guard = QuotaGuard(SafetyBudget(max_input_tpm=10, max_product_cost_usd=0.01))
    guard.reserve(Usage(input_tokens=10, cost_usd=0.01), product_id="p1")
    assert guard.check(estimated_input_tokens=1).decision is GuardDecision.QUOTA_GUARDED
    guard._token_events[0] = (time.monotonic() - 61, 10)
    assert (
        guard.check(estimated_cost_usd=0.001, product_id="p1").decision
        is GuardDecision.BUDGET_DEFERRED
    )


def test_circuit_breaker_opens_and_half_opens() -> None:
    breaker = QuotaCircuitBreaker(failure_threshold=2, cooldown_seconds=1)
    breaker.record_429(now=1)
    breaker.record_429(now=1)
    assert not breaker.allow(now=0.5)
    assert breaker.allow(now=2.1)


def test_429_metadata_takes_priority_over_search_words() -> None:
    class ProviderRateLimit(RuntimeError):
        status_code = 429
        provider_code = "too_many_requests"

    assert classify_429(ProviderRateLimit("Google Search quota")) is FailureCategory.RATE_LIMIT
    assert (
        classify_429(RuntimeError("Google Search quota exceeded")) is FailureCategory.PROJECT_QUOTA
    )
