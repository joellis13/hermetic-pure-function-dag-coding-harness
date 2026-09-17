"""Plan schemas: the structured output of the Planning compute node."""
from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


def _new_id() -> str:
    return str(uuid.uuid4())


class TaskItem(BaseModel):
    """
    A single atomic coding task.

    `dependencies` is a list of other `TaskItem.id` values that must
    complete before this task may begin. An empty list means the task
    can start immediately (in the first wave of its batch).
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=_new_id, description="Unique task ID (UUID or human-readable slug)")
    description: str = Field(..., description="One-line summary of the task for display")
    instruction: str = Field(..., description="Full LLM prompt / instruction for the Implementation Node")
    dependencies: list[str] = Field(
        default_factory=list,
        description="IDs of TaskItems that must complete before this one",
    )


class TaskBatch(BaseModel):
    """
    An ordered set of TaskItems that, together, form one logical phase of the plan.

    Within a batch, all tasks whose dependencies are already satisfied
    execute in parallel. Batches themselves execute sequentially.
    """
    model_config = ConfigDict(frozen=True)

    batch_id: str = Field(default_factory=_new_id)
    description: str = Field(default="", description="Human-readable label for this batch")
    tasks: list[TaskItem] = Field(..., min_length=1)


class PlanIterationContext(BaseModel):
    """Carries HITL feedback from one planning iteration to the next."""
    model_config = ConfigDict(frozen=True)

    iteration: int = Field(default=0, ge=0, description="0 = initial plan, 1+ = revised plan")
    feedback: str = Field(default="", description="User or Critic feedback from the previous iteration")


class ImplementationPlan(BaseModel):
    """
    The top-level artifact produced by the Planning Node.

    `batches` are ordered: batch[0] executes first, batch[1] second, etc.
    Within each batch, tasks may run concurrently per their dependency graph.
    """
    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(default_factory=_new_id)
    issue_id: str = Field(..., description="Links back to the originating IssueContext.issue_id")
    batches: list[TaskBatch] = Field(..., min_length=1)
    iteration_context: PlanIterationContext = Field(default_factory=PlanIterationContext)
