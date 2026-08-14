"""Valid ProductTruth lifecycle transitions."""

from .truth import LifecycleState

ALLOWED_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.RAW: frozenset(
        {LifecycleState.UNDERSTOOD, LifecycleState.REVIEW_REQUIRED, LifecycleState.BLOCKED}
    ),
    LifecycleState.UNDERSTOOD: frozenset(
        {LifecycleState.CLASSIFIED, LifecycleState.REVIEW_REQUIRED, LifecycleState.BLOCKED}
    ),
    LifecycleState.CLASSIFIED: frozenset(
        {LifecycleState.ENRICHED, LifecycleState.REVIEW_REQUIRED, LifecycleState.CONFLICTED}
    ),
    LifecycleState.ENRICHED: frozenset(
        {LifecycleState.VALIDATED, LifecycleState.REVIEW_REQUIRED, LifecycleState.CONFLICTED}
    ),
    LifecycleState.VALIDATED: frozenset(
        {LifecycleState.READY, LifecycleState.REVIEW_REQUIRED, LifecycleState.CONFLICTED}
    ),
    LifecycleState.READY: frozenset({LifecycleState.DELIVERED, LifecycleState.BLOCKED}),
    LifecycleState.DELIVERED: frozenset(),
    LifecycleState.REVIEW_REQUIRED: frozenset(
        {
            LifecycleState.UNDERSTOOD,
            LifecycleState.CLASSIFIED,
            LifecycleState.ENRICHED,
            LifecycleState.BLOCKED,
        }
    ),
    LifecycleState.BLOCKED: frozenset({LifecycleState.REVIEW_REQUIRED, LifecycleState.RAW}),
    LifecycleState.CONFLICTED: frozenset({LifecycleState.REVIEW_REQUIRED, LifecycleState.ENRICHED}),
}


class InvalidLifecycleTransition(ValueError):
    """Raised when a product attempts an unsupported state transition."""


def assert_transition(current: LifecycleState, target: LifecycleState) -> None:
    """Validate one transition without mutating product state."""

    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidLifecycleTransition(f"Cannot transition product from {current} to {target}")
