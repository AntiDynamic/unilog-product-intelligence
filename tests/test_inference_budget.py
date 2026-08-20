"""Unit tests for InferenceBudget and InferenceBudgetExceeded."""

from __future__ import annotations

import pytest

from unilog_product_intelligence.enrichment.inference_budget import (
    InferenceBudget,
    InferenceBudgetExceeded,
)


def test_budget_consumption_and_tracking() -> None:
    budget = InferenceBudget(max_calls=5, max_tokens=10_000, max_cost_usd=0.50)
    assert budget.can_consume(calls=1) is True

    budget.consume(phase="discovery", calls=2, tokens=1500, cost_usd=0.02)
    assert budget.calls_consumed == 2
    assert budget.tokens_consumed == 1500
    assert budget.cost_consumed_usd == 0.02
    assert budget.phase_calls["discovery"] == 2


def test_budget_exceeded_calls_raises() -> None:
    budget = InferenceBudget(max_calls=2)
    budget.consume(phase="p1", calls=2)

    assert budget.can_consume(calls=1) is False
    with pytest.raises(InferenceBudgetExceeded) as exc_info:
        budget.consume(phase="p2", calls=1)
    assert "calls=3/2" in str(exc_info.value)


def test_budget_token_limit_exceeded_raises() -> None:
    budget = InferenceBudget(max_calls=10, max_tokens=5000)
    budget.consume(phase="p1", calls=1, tokens=4000)

    assert budget.can_consume(calls=1, tokens=2000) is False
    with pytest.raises(InferenceBudgetExceeded) as exc_info:
        budget.consume(phase="p2", calls=1, tokens=2000)
    assert "tokens=6000/5000" in str(exc_info.value)


def test_budget_cost_limit_exceeded_raises() -> None:
    budget = InferenceBudget(max_calls=10, max_cost_usd=0.10)
    budget.consume(phase="p1", calls=1, cost_usd=0.08)

    assert budget.can_consume(calls=1, cost_usd=0.05) is False
    with pytest.raises(InferenceBudgetExceeded) as exc_info:
        budget.consume(phase="p2", calls=1, cost_usd=0.05)
    assert "cost=$0.1300/$0.1000" in str(exc_info.value)


def test_phase_breakdown_tracking() -> None:
    budget = InferenceBudget(max_calls=10)
    budget.consume(phase="discovery", calls=2)
    budget.consume(phase="enrichment", calls=3)
    budget.consume(phase="discovery", calls=1)

    assert budget.phase_calls == {"discovery": 3, "enrichment": 3}
    assert budget.calls_consumed == 6
