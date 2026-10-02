"""ImplementationNode: AI compute node that produces a TaskDeliverable from a TaskItem."""
from __future__ import annotations

import json

from hermetic.compute.driver import AgentDriver, NodeExecutionMetadata
from hermetic.data.sanitizer import SanitizationError, sanitize_json
from hermetic.schemas.deliverable import TaskDeliverable, TaskRetryContext
from hermetic.schemas.plan import TaskItem


class ImplementationError(Exception):
    """Raised when the AI response cannot be parsed into a valid TaskDeliverable."""

    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


_IMPLEMENTATION_SYSTEM_PROMPT = f"""You are an expert software engineer.
Given a coding task instruction, produce a structured TaskDeliverable as a single valid JSON object.
No prose before or after the JSON. No markdown fences.

The deliverable must conform exactly to this schema:
{json.dumps(TaskDeliverable.model_json_schema(), indent=2)}

Rules:
- edits must be exact search-and-replace operations using verbatim strings from the existing file.
- search_string must appear exactly expected_occurrences times in the file.
- explanation should briefly describe what was changed and why.
- task_id must match the task ID provided in the prompt.
"""


def _build_implementation_prompt(
    task: TaskItem,
    retry_context: TaskRetryContext | None = None,
) -> str:
    parts = [
        f"Task ID: {task.id}",
        f"Description: {task.description}",
        "",
        "Instruction:",
        task.instruction,
    ]

    if retry_context is not None:
        parts.append("")
        parts.append(f"RETRY ATTEMPT {retry_context.retry_count + 1} — Previous attempt failed with error:")
        parts.append(retry_context.error_message)
        if retry_context.previous_deliverable is not None:
            parts.append("")
            parts.append("Previous (failed) deliverable for reference:")
            parts.append(retry_context.previous_deliverable.model_dump_json(indent=2))

    return "\n".join(parts)


class ImplementationNode:
    """Invokes an AgentDriver to generate a TaskDeliverable from a TaskItem."""

    def __init__(self, driver: AgentDriver) -> None:
        self._driver = driver

    async def implement(
        self,
        task: TaskItem,
        retry_context: TaskRetryContext | None = None,
    ) -> tuple[TaskDeliverable, NodeExecutionMetadata]:
        """
        Call the driver, sanitize output, parse as TaskDeliverable.
        Raises ImplementationError if the response cannot be parsed.
        retry_context=None means first attempt.
        """
        prompt = _build_implementation_prompt(task, retry_context)
        system = _IMPLEMENTATION_SYSTEM_PROMPT

        raw_text, meta = await self._driver.invoke(prompt, system)

        clean = sanitize_json(raw_text)
        if isinstance(clean, SanitizationError):
            raise ImplementationError(
                f"Sanitization failed: {clean.error_message}",
                raw_response=raw_text,
            )

        try:
            data = json.loads(clean)
            # Inject task_id if model omitted it
            if isinstance(data, dict) and "task_id" not in data:
                data["task_id"] = task.id
            deliverable = TaskDeliverable.model_validate(data)
        except Exception as exc:
            raise ImplementationError(
                f"Deliverable validation failed: {exc}",
                raw_response=raw_text,
            ) from exc

        if deliverable.task_id != task.id:
            deliverable = deliverable.model_copy(update={"task_id": task.id})

        return deliverable, meta
