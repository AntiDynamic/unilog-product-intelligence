"""Deterministic request-reduction helpers used before Gemini execution."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .scale import CostConfig, cache_key


@dataclass(frozen=True)
class SearchCacheEntry:
    manufacturer: str
    status: str
    domain: str | None
    query_fingerprint: str
    expires_at: float

    def valid(self, now: float | None = None) -> bool:
        return (now or time.time()) < self.expires_at


class ManufacturerSearchCache:
    def __init__(self, negative_ttl_seconds: int = 86_400) -> None:
        self.negative_ttl_seconds = negative_ttl_seconds
        self._entries: dict[str, SearchCacheEntry] = {}

    def get(self, manufacturer: str) -> SearchCacheEntry | None:
        entry = self._entries.get(manufacturer.casefold())
        return entry if entry and entry.valid() else None

    def put(
        self,
        manufacturer: str,
        status: str,
        domain: str | None,
        query: str,
        ttl_seconds: int | None = None,
    ) -> SearchCacheEntry:
        entry = SearchCacheEntry(
            manufacturer,
            status,
            domain,
            cache_key(manufacturer.casefold(), query),
            time.time() + (ttl_seconds or self.negative_ttl_seconds),
        )
        self._entries[manufacturer.casefold()] = entry
        return entry


def group_manufacturers(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        key = row.get("Part_Manuf", "").strip().casefold()
        groups.setdefault(key, []).append(row)
    return groups


def cost_scenarios(
    products: int,
    avg_input: int = 800,
    avg_output: int = 300,
    manufacturers: int = 0,
    cost: CostConfig | None = None,
) -> dict[str, dict[str, float | int | None]]:
    pricing = cost or CostConfig()
    base_input = products * avg_input
    base_output = products * avg_output
    return {
        "deterministic_only": {
            "gemini_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
        },
        "gemini_no_cache": {
            "gemini_calls": products,
            "input_tokens": base_input,
            "output_tokens": base_output,
            "cost_usd": pricing.estimate(base_input, base_output),
        },
        "implicit_cache_25pct": {
            "gemini_calls": products,
            "input_tokens": base_input,
            "output_tokens": base_output,
            "cached_tokens": int(base_input * 0.25),
            "cost_usd": pricing.estimate(int(base_input * 0.75), base_output),
        },
        "batch_50pct_model_discount": {
            "gemini_calls": products,
            "input_tokens": base_input,
            "output_tokens": base_output,
            "cost_usd": (pricing.estimate(base_input, base_output) or 0) * 0.5,
        },
        "search_queries": {"manufacturer_groups": manufacturers},
    }
