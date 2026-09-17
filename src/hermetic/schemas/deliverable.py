"""Deliverable schemas: the structured output produced by an Implementation compute node."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StructuredFileEdit(BaseModel):
    """
    A deterministic search-and-replace file edit.

    The Implementation Node emits these; the Data Plane applier executes them.
    `expected_occurrences` guards against accidental multi-match: the applier
    verifies the exact count before committing any change.
    """
    model_config = ConfigDict(frozen=True)

    file_path: str = Field(..., description="Repo-relative path of the file to edit")
    search_string: str = Field(..., description="Exact string to locate in the file (verbatim)")
    replacement_string: str = Field(..., description="Exact replacement for every matched occurrence")
    expected_occurrences: int = Field(
        default=1,
        ge=1,
        description="The applier will reject the edit if this many occurrences are not found",
    )


class TaskDeliverable(BaseModel):
    """All edits produced by one TaskItem execution."""
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(..., description="ID of the TaskItem this deliverable satisfies")
    edits: list[StructuredFileEdit] = Field(default_factory=list)
    explanation: str = Field(default="", description="Optional reasoning from the Implementation Node")


class TaskRetryContext(BaseModel):
    """
    Feedback fed back to the Implementation Node on a retry.

    Contains the original TaskItem instruction, the previous deliverable that
    failed, and the error message (lint/test output) so the model can self-correct.
    """
    model_config = ConfigDict(frozen=True)

    task_id: str
    error_message: str = Field(..., description="Linter / test failure output to show the model")
    retry_count: int = Field(..., ge=0, le=3, description="0-indexed; max 3 retries (hard cap)")
    previous_deliverable: TaskDeliverable | None = Field(
        default=None,
        description="The deliverable from the last failed attempt, for context",
    )


class FullImplementationReport(BaseModel):
    """
    Aggregated result of an entire plan execution run.

    Serializes to JSON and is also the data model for `full_report.html`.
    """
    model_config = ConfigDict(frozen=True)

    plan_id: str
    deliverables: list[TaskDeliverable] = Field(default_factory=list)
    failed_tasks: list[str] = Field(default_factory=list, description="task_ids that exhausted all retries")
    summary: str = Field(default="")
    total_input_tokens: int = Field(default=0, ge=0)
    total_output_tokens: int = Field(default=0, ge=0)
