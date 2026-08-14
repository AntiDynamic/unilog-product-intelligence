"""Central model selection for future controlled escalation."""

from unilog_product_intelligence.config import GEMINI_MODEL


class ModelRouter:
    """Routes every supported Phase 4 task to the pinned primary model."""

    _tasks = frozenset({"product_understanding", "classification", "attribute_extraction"})

    def model_for(self, task: str) -> str:
        if task not in self._tasks:
            raise ValueError(f"Unsupported model task: {task}")
        return GEMINI_MODEL
