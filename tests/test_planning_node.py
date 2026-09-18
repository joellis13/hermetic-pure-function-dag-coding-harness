"""Tests for PlanningNode and PlanningError."""
from __future__ import annotations

import json

import pytest

from hermetic.compute.driver import AgentDriver, MockDriver, NodeExecutionMetadata
from hermetic.compute.planning_node import PlanningError, PlanningNode
from hermetic.schemas.context import CodeSnippet, ExternalDoc, IssueContext
from hermetic.schemas.plan import ImplementationPlan, PlanIterationContext


class CapturingMockDriver(AgentDriver):
    """MockDriver that captures the prompt and system strings passed to invoke."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.last_prompt: str | None = None
        self.last_system: str | None = None

    async def invoke(
        self, prompt: str, system: str
    ) -> tuple[str, NodeExecutionMetadata]:
        self.last_prompt = prompt
        self.last_system = system
        return self.response, NodeExecutionMetadata(
            input_tokens=len(prompt) // 4,
            output_tokens=len(self.response) // 4,
            latency_ms=10.0,
            model_name="mock-capturing",
        )


@pytest.fixture
def sample_context() -> IssueContext:
    return IssueContext(
        issue_id="GH-10",
        title="Add user authentication",
        description="We need JWT-based auth for the API.",
        snippets=[
            CodeSnippet(
                file_path="src/auth.py",
                content="def verify(): pass",
                start_line=1,
                end_line=1,
            )
        ],
        docs=[
            ExternalDoc(
                url="https://example.com/spec",
                content="Auth specification text",
                title="Auth Spec",
            )
        ],
    )


@pytest.fixture
def valid_plan_json() -> str:
    return json.dumps(
        {
            "plan_id": "plan-123",
            "issue_id": "GH-10",
            "batches": [
                {
                    "batch_id": "batch-1",
                    "description": "Auth foundations",
                    "tasks": [
                        {
                            "id": "task-1",
                            "description": "Implement token generator",
                            "instruction": "Generate JWT with HS256",
                            "dependencies": [],
                        }
                    ],
                }
            ],
        }
    )


class TestPlanningNode:
    async def test_plan_returns_implementation_plan(
        self, sample_context: IssueContext, valid_plan_json: str
    ) -> None:
        driver = MockDriver(response=valid_plan_json)
        node = PlanningNode(driver=driver)
        plan, _ = await node.plan(sample_context)

        assert isinstance(plan, ImplementationPlan)
        assert plan.plan_id == "plan-123"
        assert plan.issue_id == "GH-10"
        assert len(plan.batches) == 1
        assert plan.batches[0].tasks[0].id == "task-1"

    async def test_plan_returns_node_execution_metadata(
        self, sample_context: IssueContext, valid_plan_json: str
    ) -> None:
        driver = MockDriver(response=valid_plan_json)
        node = PlanningNode(driver=driver)
        _, meta = await node.plan(sample_context)

        assert isinstance(meta, NodeExecutionMetadata)
        assert meta.output_tokens > 0

    async def test_plan_with_iteration_context_injects_feedback_in_prompt(
        self, sample_context: IssueContext, valid_plan_json: str
    ) -> None:
        driver = CapturingMockDriver(response=valid_plan_json)
        node = PlanningNode(driver=driver)
        iteration = PlanIterationContext(
            iteration=1,
            feedback="Please add unit tests for token expiration",
        )
        await node.plan(sample_context, iteration=iteration)

        assert driver.last_prompt is not None
        assert "Feedback from previous iteration (iteration 1):" in driver.last_prompt
        assert "Please add unit tests for token expiration" in driver.last_prompt

    async def test_plan_first_iteration_omits_feedback_section(
        self, sample_context: IssueContext, valid_plan_json: str
    ) -> None:
        driver = CapturingMockDriver(response=valid_plan_json)
        node = PlanningNode(driver=driver)

        # Case 1: iteration is None
        await node.plan(sample_context, iteration=None)
        assert driver.last_prompt is not None
        assert "Feedback from previous iteration" not in driver.last_prompt

        # Case 2: iteration has empty feedback
        empty_iter = PlanIterationContext(iteration=0, feedback="")
        await node.plan(sample_context, iteration=empty_iter)
        assert "Feedback from previous iteration" not in driver.last_prompt

    async def test_plan_raises_planning_error_on_sanitization_failure(
        self, sample_context: IssueContext
    ) -> None:
        driver = MockDriver(response="This is not valid JSON and has no braces at all.")
        node = PlanningNode(driver=driver)

        with pytest.raises(PlanningError) as exc_info:
            await node.plan(sample_context)

        assert "Sanitization failed" in str(exc_info.value)
        assert exc_info.value.raw_response == "This is not valid JSON and has no braces at all."

    async def test_plan_raises_planning_error_on_invalid_schema(
        self, sample_context: IssueContext
    ) -> None:
        invalid_schema_json = json.dumps({"something_else": 123})
        driver = MockDriver(response=invalid_schema_json)
        node = PlanningNode(driver=driver)

        with pytest.raises(PlanningError) as exc_info:
            await node.plan(sample_context)

        assert "Plan validation failed" in str(exc_info.value)
        assert exc_info.value.raw_response == invalid_schema_json

    async def test_plan_sets_issue_id_from_context(
        self, sample_context: IssueContext
    ) -> None:
        # Response has different issue_id
        plan_with_wrong_id = json.dumps(
            {
                "plan_id": "plan-456",
                "issue_id": "GH-DIFFERENT",
                "batches": [
                    {
                        "batch_id": "batch-1",
                        "description": "Batch",
                        "tasks": [
                            {
                                "id": "task-1",
                                "description": "T",
                                "instruction": "Inst",
                                "dependencies": [],
                            }
                        ],
                    }
                ],
            }
        )
        driver = MockDriver(response=plan_with_wrong_id)
        node = PlanningNode(driver=driver)
        plan, _ = await node.plan(sample_context)

        assert plan.issue_id == sample_context.issue_id
