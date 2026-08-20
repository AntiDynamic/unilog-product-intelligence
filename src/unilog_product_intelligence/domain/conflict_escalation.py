"""ConflictEscalationResult: the outcome of Gemini choosing between competing evidence.

Gemini selects an existing evidence record — it does not create evidence or change
authority. This invariant is enforced at construction time:

  selected_evidence_id must be in the supporting_evidence_ids tuple.

If Gemini returns an ID that is not in the packet, selected_evidence_id and
selected_value are set to None and the conflict becomes REVIEW_REQUIRED.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConflictEscalationResult(BaseModel):
    """Result of escalating a conflict to a stronger Gemini model.

    Gemini selects between *existing* evidence records — it does not invent new ones.

    Invariant
    ---------
    `selected_evidence_id` must be present in `supporting_evidence_ids`, or must
    be `None` (when the model was unable to make a determination).

    If callers detect that the returned `selected_evidence_id` is not in the packet
    they should use `ConflictEscalationResult.with_nulled_selection()` to produce a
    safe, REVIEW_REQUIRED-compatible result.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    attribute: str = Field(description="Attribute name that was in conflict")
    # None means the model could not make a determination; conflict becomes REVIEW_REQUIRED.
    selected_evidence_id: str | None = Field(
        default=None,
        description="Evidence ID selected by the model — must be in supporting_evidence_ids",
    )
    selected_value: str | None = Field(
        default=None,
        description="Value from the selected evidence record",
    )
    reasoning: str = Field(description="Model explanation for why this evidence was selected")
    model_name: str = Field(description="Name of the model that resolved the escalation")
    supporting_evidence_ids: tuple[str, ...] = Field(
        default=(),
        description="All evidence IDs that were considered during escalation",
    )

    @model_validator(mode="after")
    def _validate_selection_in_supporting(self) -> ConflictEscalationResult:
        if (
            self.selected_evidence_id is not None
            and self.selected_evidence_id not in self.supporting_evidence_ids
        ):
            raise ValueError(
                f"selected_evidence_id {self.selected_evidence_id!r} is not in "
                f"supporting_evidence_ids {self.supporting_evidence_ids!r}. "
                "Gemini may only select from existing evidence, not invent new records."
            )
        return self

    @classmethod
    def with_nulled_selection(
        cls,
        attribute: str,
        reasoning: str,
        model_name: str,
        supporting_evidence_ids: tuple[str, ...],
    ) -> ConflictEscalationResult:
        """Build an escalation result where no valid selection could be made.

        Use when the model returned an evidence ID that is not in the packet.
        The result signals REVIEW_REQUIRED without making a selection.
        """
        return cls(
            attribute=attribute,
            selected_evidence_id=None,
            selected_value=None,
            reasoning=reasoning,
            model_name=model_name,
            supporting_evidence_ids=supporting_evidence_ids,
        )


__all__ = ["ConflictEscalationResult"]
