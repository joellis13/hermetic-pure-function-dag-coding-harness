"""Review schemas: the structured output of the Critic compute node."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from hermetic.schemas.deliverable import StructuredFileEdit


class ReviewFeedback(BaseModel):
    """
    Structured verdict from the Critic Node.

    If `approved` is False, `comments` and `suggested_changes` are fed
    back into the next planning iteration via `PlanIterationContext.feedback`.
    """
    model_config = ConfigDict(frozen=True)

    approved: bool = Field(..., description="True = plan is accepted; False = revision required")
    comments: str = Field(default="", description="Explanation of the verdict")
    suggested_changes: list[StructuredFileEdit] = Field(
        default_factory=list,
        description="Concrete edits the Critic recommends (may be empty even on rejection)",
    )
