"""PlanningNode: AI compute node that produces an ImplementationPlan."""
from __future__ import annotations

import json

from hermetic.compute.driver import AgentDriver, NodeExecutionMetadata
from hermetic.data.sanitizer import SanitizationError, sanitize_json
from hermetic.schemas.context import IssueContext
from hermetic.schemas.plan import ImplementationPlan, PlanIterationContext


class PlanningError(Exception):
    """Raised when the AI response cannot be parsed into a valid ImplementationPlan."""

    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


_PLANNING_SYSTEM_PROMPT = f"""You are an expert software engineering planner.
Given an issue context, produce a structured ImplementationPlan as a single valid JSON object.
No prose before or after the JSON. No markdown fences.

The plan must conform exactly to this schema:
{json.dumps(ImplementationPlan.model_json_schema(), indent=2)}

Rules:
- Split work into sequential TaskBatches. Tasks within a batch run concurrently.
- Each TaskItem.instruction must be a complete, self-contained prompt for an implementation model.
- Use dependency IDs only for tasks within the same batch.
- issue_id must equal the IssueContext.issue_id.
"""


def _build_planning_prompt(
    context: IssueContext,
    iteration: PlanIterationContext | None = None,
) -> str:
    parts = [
        f"Issue ID: {context.issue_id}",
        f"Title: {context.title}",
        "",
        "Description:",
        context.description,
    ]

    if context.snippets:
        parts.append("")
        parts.append("Code Snippets:")
        for snippet in context.snippets:
            parts.append(
                f"--- Snippet: {snippet.file_path} (lines {snippet.start_line}-{snippet.end_line}) ---"
            )
            parts.append(snippet.content)

    if context.docs:
        parts.append("")
        parts.append("External Documentation:")
        for doc in context.docs:
            header = (
                f"--- Doc: {doc.title} ({doc.url}) ---"
                if doc.title
                else f"--- Doc: {doc.url} ---"
            )
            parts.append(header)
            parts.append(doc.content)

    if iteration is not None and iteration.feedback and iteration.feedback.strip():
        parts.append("")
        parts.append(f"Feedback from previous iteration (iteration {iteration.iteration}):")
        parts.append(iteration.feedback.strip())

    return "\n".join(parts)


class PlanningNode:
    """Invokes an AgentDriver to generate an ImplementationPlan from an IssueContext."""

    def __init__(self, driver: AgentDriver) -> None:
        self._driver = driver

    async def plan(
        self,
        context: IssueContext,
        iteration: PlanIterationContext | None = None,
    ) -> tuple[ImplementationPlan, NodeExecutionMetadata]:
        """
        Call the driver, sanitize output, parse as ImplementationPlan.
        Raises PlanningError if the response cannot be parsed.
        iteration=None → first plan (no feedback section in prompt).
        """
        prompt = _build_planning_prompt(context, iteration)
        system = _PLANNING_SYSTEM_PROMPT

        raw_text, meta = await self._driver.invoke(prompt, system)

        clean = sanitize_json(raw_text)
        if isinstance(clean, SanitizationError):
            raise PlanningError(
                f"Sanitization failed: {clean.error_message}",
                raw_response=raw_text,
            )

        try:
            data = json.loads(clean)
            if isinstance(data, dict) and "issue_id" not in data:
                data["issue_id"] = context.issue_id
            plan = ImplementationPlan.model_validate(data)
        except Exception as exc:
            raise PlanningError(
                f"Plan validation failed: {exc}",
                raw_response=raw_text,
            ) from exc

        if plan.issue_id != context.issue_id:
            plan = plan.model_copy(update={"issue_id": context.issue_id})

        if iteration is not None and plan.iteration_context.iteration == 0:
            plan = plan.model_copy(update={"iteration_context": iteration})

        return plan, meta
