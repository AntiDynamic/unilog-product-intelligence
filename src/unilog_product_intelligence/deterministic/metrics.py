"""Small deterministic operation metrics; no accuracy claims."""

from collections import Counter
from dataclasses import dataclass, field

from .registry import ResolutionStatus


@dataclass
class DeterministicMetrics:
    counts: Counter[str] = field(default_factory=Counter)

    def record_resolution(self, operation: str, status: ResolutionStatus) -> None:
        self.counts[f"{operation}.{status.value}"] += 1

    def record(self, name: str) -> None:
        self.counts[name] += 1

    def as_dict(self) -> dict[str, int]:
        return dict(sorted(self.counts.items()))
