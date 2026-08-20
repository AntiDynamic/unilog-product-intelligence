"""Inference budget tracking and enforcement per product workflow."""

from __future__ import annotations

from dataclasses import dataclass, field


class InferenceBudgetExceeded(RuntimeError):
    """Raised when an operation exceeds the allocated inference call or token budget."""


@dataclass
class InferenceBudget:
    """Per-product, per-run inference budget limiting LLM calls and token spend.

    Attributes
    ----------
    max_calls:
        Maximum total LLM calls allowed across all phases for this product (default 10).
    max_tokens:
        Maximum total tokens allowed across all calls (default 100,000).
    max_cost_usd:
        Maximum estimated cost in USD (default .00).
    calls_consumed:
        Current number of calls made.
    tokens_consumed:
        Current number of tokens consumed across calls.
    cost_consumed_usd:
        Current estimated cost in USD consumed.
    phase_calls:
        Breakdown of calls consumed per workflow phase (e.g. 'discovery', 'enrichment').
    """

    max_calls: int = 10
    max_tokens: int = 100_000
    max_cost_usd: float = 1.0
    calls_consumed: int = 0
    tokens_consumed: int = 0
    cost_consumed_usd: float = 0.0
    phase_calls: dict[str, int] = field(default_factory=dict)

    def can_consume(self, calls: int = 1, tokens: int = 0, cost_usd: float = 0.0) -> bool:
        """Check whether consuming the given resources would exceed the budget."""
        if self.calls_consumed + calls > self.max_calls:
            return False
        if tokens > 0 and self.tokens_consumed + tokens > self.max_tokens:
            return False
        return not (cost_usd > 0.0 and self.cost_consumed_usd + cost_usd > self.max_cost_usd)

    def consume(
        self,
        phase: str = "general",
        calls: int = 1,
        tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Record resource consumption against the budget, raising if exceeded."""
        if not self.can_consume(calls=calls, tokens=tokens, cost_usd=cost_usd):
            raise InferenceBudgetExceeded(
                f"Inference budget exceeded: calls={self.calls_consumed + calls}/{self.max_calls}, "
                f"tokens={self.tokens_consumed + tokens}/{self.max_tokens}, "
                f"cost=${self.cost_consumed_usd + cost_usd:.4f}/${self.max_cost_usd:.4f}"
            )
        self.calls_consumed += calls
        self.tokens_consumed += max(0, tokens)
        self.cost_consumed_usd += max(0.0, cost_usd)
        self.phase_calls[phase] = self.phase_calls.get(phase, 0) + calls


__all__ = ["InferenceBudget", "InferenceBudgetExceeded"]
