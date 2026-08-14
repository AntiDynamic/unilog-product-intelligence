"""Quota-aware execution primitives for interactive and bulk Gemini work."""

from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Any


class TaskClass(StrEnum):
    INTERACTIVE = "INTERACTIVE"
    BATCHABLE = "BATCHABLE"
    NON_AI = "NON_AI"
    EXTERNAL_DISCOVERY = "EXTERNAL_DISCOVERY"


class ExecutionMode(StrEnum):
    INTERACTIONS = "INTERACTIONS"
    BATCH = "BATCH"
    DETERMINISTIC = "DETERMINISTIC"


class GuardDecision(StrEnum):
    ALLOW = "ALLOW"
    QUOTA_GUARDED = "QUOTA_GUARDED"
    BUDGET_DEFERRED = "BUDGET_DEFERRED"


class QuotaDimension(StrEnum):
    RPM = "RPM"
    TPM = "TPM"
    RPD = "RPD"
    SPEND = "SPEND"
    PROJECT_QUOTA = "PROJECT_QUOTA"
    SEARCH = "SEARCH"
    UNKNOWN = "UNKNOWN"


class FailureCategory(StrEnum):
    RATE_LIMIT = "RATE_LIMIT"
    SPEND_LIMIT = "SPEND_LIMIT"
    SEARCH_LIMIT = "SEARCH_LIMIT"
    PROJECT_QUOTA = "PROJECT_QUOTA"
    CAPACITY = "CAPACITY"
    UNKNOWN_429 = "UNKNOWN_429"


@dataclass(frozen=True)
class SafetyBudget:
    max_rpm: int = 5
    max_input_tpm: int = 100_000
    max_daily_requests: int = 500
    max_search_queries: int = 50
    max_daily_cost_usd: float = 5.0
    max_product_cost_usd: float = 0.25
    max_concurrency: int = 2
    retry_max_attempts: int = 3


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    search_queries: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class GuardResult:
    decision: GuardDecision
    reason: str | None = None


class QuotaGuard:
    """Local safety guard with rolling RPM/TPM and daily/product budgets."""

    provider_limits: dict[str, str] = {"rpm": "UNKNOWN", "input_tpm": "UNKNOWN", "rpd": "UNKNOWN"}

    def __init__(self, budget: SafetyBudget | None = None) -> None:
        self.budget = budget or SafetyBudget()
        self._requests: deque[float] = deque()
        self._token_events: deque[tuple[float, int]] = deque()
        self._usage = Usage()
        self._daily_requests = 0
        self._daily_cost = 0.0
        self._product_costs: dict[str, float] = {}
        self._lock = Lock()

    @property
    def usage(self) -> Usage:
        return self._usage

    def check(
        self,
        estimated_input_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        search_queries: int = 0,
        product_id: str | None = None,
    ) -> GuardResult:
        with self._lock:
            now = time.monotonic()
            while self._requests and now - self._requests[0] >= 60:
                self._requests.popleft()
            while self._token_events and now - self._token_events[0][0] >= 60:
                self._token_events.popleft()
            rolling_tokens = sum(tokens for _, tokens in self._token_events)
            if (
                len(self._requests) >= self.budget.max_rpm
                or rolling_tokens + estimated_input_tokens > self.budget.max_input_tpm
            ):
                return GuardResult(GuardDecision.QUOTA_GUARDED, "local_rate_or_token_safety_limit")
            if (
                self._daily_requests >= self.budget.max_daily_requests
                or self._daily_cost + estimated_cost_usd > self.budget.max_daily_cost_usd
            ):
                return GuardResult(GuardDecision.BUDGET_DEFERRED, "local_daily_budget")
            if self._usage.search_queries + search_queries > self.budget.max_search_queries:
                return GuardResult(GuardDecision.BUDGET_DEFERRED, "local_search_budget")
            if (
                product_id is not None
                and self._product_costs.get(product_id, 0.0) + estimated_cost_usd
                > self.budget.max_product_cost_usd
            ):
                return GuardResult(GuardDecision.BUDGET_DEFERRED, "local_product_budget")
            return GuardResult(GuardDecision.ALLOW)

    def reserve(self, usage: Usage, product_id: str | None = None) -> None:
        with self._lock:
            now = time.monotonic()
            self._requests.append(now)
            self._token_events.append((now, usage.input_tokens))
            self._daily_requests += 1
            self._daily_cost += usage.cost_usd
            if product_id is not None:
                self._product_costs[product_id] = (
                    self._product_costs.get(product_id, 0.0) + usage.cost_usd
                )
            self._usage = Usage(
                self._usage.input_tokens + usage.input_tokens,
                self._usage.output_tokens + usage.output_tokens,
                self._usage.cached_tokens + usage.cached_tokens,
                self._usage.search_queries + usage.search_queries,
                self._usage.cost_usd + usage.cost_usd,
            )


class SearchBudget:
    def __init__(self, max_queries: int = 50) -> None:
        self.max_queries = max_queries
        self.queries = 0
        self.manufacturers: set[str] = set()

    def allow(self, manufacturer: str) -> bool:
        return self.queries < self.max_queries and manufacturer.casefold() not in self.manufacturers

    def record(self, manufacturer: str, queries: int = 1) -> None:
        self.queries += queries
        self.manufacturers.add(manufacturer.casefold())


class ModelExecutionRouter:
    def route(
        self,
        task_class: TaskClass,
        product_count: int = 1,
        needs_tools: bool = False,
        needs_state: bool = False,
    ) -> ExecutionMode:
        if task_class is TaskClass.NON_AI:
            return ExecutionMode.DETERMINISTIC
        if needs_tools or needs_state or task_class is TaskClass.INTERACTIVE or product_count <= 1:
            return ExecutionMode.INTERACTIONS
        return (
            ExecutionMode.BATCH if task_class is TaskClass.BATCHABLE else ExecutionMode.INTERACTIONS
        )


def classify_task(task: str) -> TaskClass:
    normalized = task.casefold()
    if any(x in normalized for x in ("normalize", "uom", "validate", "placeholder", "lookup")):
        return TaskClass.NON_AI
    if any(x in normalized for x in ("search", "discover", "manufacturer", "source")):
        return TaskClass.EXTERNAL_DISCOVERY
    return TaskClass.BATCHABLE


def task_fingerprint(
    product_identity: str,
    task: str,
    prompt_version: str,
    evidence_hash: str = "",
    schema_version: str = "",
) -> str:
    value = "|".join((product_identity, task, prompt_version, evidence_hash, schema_version))
    return hashlib.sha256(value.encode()).hexdigest()


def classify_429(error: BaseException) -> FailureCategory:
    text = str(error).casefold()
    if any(x in text for x in ("search", "grounding")):
        return FailureCategory.SEARCH_LIMIT
    if any(x in text for x in ("spend", "billing", "budget")):
        return FailureCategory.SPEND_LIMIT
    if any(x in text for x in ("capacity", "overloaded")):
        return FailureCategory.CAPACITY
    if any(x in text for x in ("quota", "project")):
        return FailureCategory.PROJECT_QUOTA
    if "too_many" in text or "rate" in text:
        return FailureCategory.RATE_LIMIT
    return FailureCategory.UNKNOWN_429


@dataclass(frozen=True)
class CostConfig:
    input_per_million_usd: float = 0.30
    output_per_million_usd: float = 2.50
    search_query_usd: float | None = None
    effective_date: str = "2026-08-14"
    source: str = "https://ai.google.dev/gemini-api/docs/pricing"

    def estimate(
        self, input_tokens: int, output_tokens: int, search_queries: int = 0
    ) -> float | None:
        token_cost = (
            input_tokens / 1_000_000 * self.input_per_million_usd
            + output_tokens / 1_000_000 * self.output_per_million_usd
        )
        if self.search_query_usd is None and search_queries:
            return None
        return token_cost + search_queries * (self.search_query_usd or 0)


def estimate_batch(
    products: int,
    avg_input_tokens: int = 800,
    avg_output_tokens: int = 300,
    manufacturers: int = 0,
    cost: CostConfig | None = None,
) -> dict[str, Any]:
    cost = cost or CostConfig()
    input_tokens = products * avg_input_tokens
    output_tokens = products * avg_output_tokens
    return {
        "products": products,
        "estimated_gemini_calls": products,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_search_queries": manufacturers,
        "estimated_cost_usd": cost.estimate(input_tokens, output_tokens, manufacturers),
        "recommended_execution_mode": ExecutionMode.BATCH.value
        if products > 1
        else ExecutionMode.INTERACTIONS.value,
    }


@dataclass(frozen=True)
class TokenUsage:
    """Unified provider telemetry; unavailable fields remain None."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    tool_use_tokens: int | None = None
    thought_tokens: int | None = None
    total_tokens: int | None = None

    @property
    def cache_hit_ratio(self) -> float | None:
        input_tokens = self.input_tokens
        cached_tokens = self.cached_input_tokens
        if input_tokens is None or input_tokens == 0 or cached_tokens is None:
            return None
        return cached_tokens / input_tokens


@dataclass(frozen=True)
class TokenBudget:
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None

    def check(self, estimated_input: int, estimated_output: int) -> GuardResult:
        if self.max_input_tokens is not None and estimated_input > self.max_input_tokens:
            return GuardResult(GuardDecision.BUDGET_DEFERRED, "TOKEN_BUDGET_DEFERRED_INPUT")
        if self.max_output_tokens is not None and estimated_output > self.max_output_tokens:
            return GuardResult(GuardDecision.BUDGET_DEFERRED, "TOKEN_BUDGET_DEFERRED_OUTPUT")
        if (
            self.max_total_tokens is not None
            and estimated_input + estimated_output > self.max_total_tokens
        ):
            return GuardResult(GuardDecision.BUDGET_DEFERRED, "TOKEN_BUDGET_DEFERRED_TOTAL")
        return GuardResult(GuardDecision.ALLOW)


class EvidenceSelector:
    """Select compact, attribute-relevant evidence without blind truncation."""

    KEYWORDS = {
        "material": ("material", "steel", "aluminum", "plastic"),
        "dimensions": ("dimension", "size", "length", "width", "height", "diameter"),
        "quantity": ("quantity", "pack", "count", "each"),
        "voltage": ("voltage", "volt", "vdc", "vac"),
        "color": ("color", "finish", "black", "white"),
    }

    def select(self, chunks: list[str], attributes: list[str], max_chunks: int = 4) -> list[str]:
        terms = tuple(
            term
            for attr in attributes
            for term in self.KEYWORDS.get(attr.casefold(), (attr.casefold(),))
        )
        scored = sorted(
            (
                (sum(term in chunk.casefold() for term in terms), index, chunk)
                for index, chunk in enumerate(chunks)
            ),
            reverse=True,
        )
        selected = [chunk for score, _, chunk in scored if score > 0][:max_chunks]
        return selected or chunks[:max_chunks]


class PromptCompressor:
    """Stable compact prompt envelope; variable context comes last."""

    def compress(self, task: str, constraints: list[str], context: str) -> str:
        rules = "; ".join(dict.fromkeys(rule.strip() for rule in constraints if rule.strip()))
        return f"TASK:{task}\nRULES:{rules}\nCONTEXT:{context.strip()}"


def cache_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def estimate_context_tokens(text: str) -> int:
    """Conservative local estimate used before provider count_tokens."""
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True)
class Provider429:
    http_status: int = 429
    provider_error_code: str | None = None
    provider_message: str | None = None
    retryable: bool = False
    quota_dimension: QuotaDimension = QuotaDimension.UNKNOWN
    retry_after_seconds: float | None = None
    request_id: str | None = None


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class QuotaCircuitBreaker:
    """Provider-scoped breaker that defers work after repeated 429s."""

    def __init__(self, failure_threshold: int = 2, cooldown_seconds: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failures = 0
        self.opened_at: float | None = None
        self.state = CircuitState.CLOSED

    def allow(self, now: float | None = None) -> bool:
        current = now or time.monotonic()
        if (
            self.state is CircuitState.OPEN
            and self.opened_at is not None
            and current - self.opened_at >= self.cooldown_seconds
        ):
            self.state = CircuitState.HALF_OPEN
        return self.state is not CircuitState.OPEN

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.state = CircuitState.CLOSED

    def record_429(self, now: float | None = None) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = now or time.monotonic()
