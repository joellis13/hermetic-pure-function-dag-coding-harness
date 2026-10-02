"""Tests for ImplementationNode compute node."""
from __future__ import annotations

import json
import pytest

from hermetic.compute.driver import AgentDriver, MockDriver, NodeExecutionMetadata
from hermetic.compute.implementation_node import ImplementationError, ImplementationNode
from hermetic.schemas.deliverable import TaskDeliverable, TaskRetryContext
from hermetic.schemas.plan import TaskItem


class SpyDriver(AgentDriver):
    def __init__(self, response: str) -> None:
        self.last_prompt = ""
        self.last_system = ""
        self._response = response

    async def invoke(self, prompt: str, system: str) -> tuple[str, NodeExecutionMetadata]:
        self.last_prompt = prompt
        self.last_system = system
        return self._response, NodeExecutionMetadata(
            input_tokens=10, output_tokens=5, latency_ms=1.0, model_name="spy"
        )


@pytest.fixture
def sample_task() -> TaskItem:
    return TaskItem(
        id="task-101",
        description="Add greeting function",
        instruction="In file.py, replace pass with return 'hi'",
        dependencies=[],
    )


@pytest.fixture
def valid_deliverable_dict() -> dict:
    return {
        "task_id": "task-101",
        "edits": [
            {
                "file_path": "file.py",
                "search_string": "pass",
                "replacement_string": "return 'hi'",
                "expected_occurrences": 1,
            }
        ],
        "explanation": "Added greeting function",
    }


class TestImplementationNode:
    async def test_implement_happy_path(
        self, sample_task: TaskItem, valid_deliverable_dict: dict
    ) -> None:
        driver = MockDriver(response=json.dumps(valid_deliverable_dict))
        node = ImplementationNode(driver)
        deliverable, meta = await node.implement(sample_task)
        assert isinstance(deliverable, TaskDeliverable)
        assert deliverable.task_id == sample_task.id
        assert len(deliverable.edits) == 1
        assert deliverable.edits[0].file_path == "file.py"

    async def test_implement_with_retry_context_appends_error(
        self, sample_task: TaskItem, valid_deliverable_dict: dict
    ) -> None:
        spy = SpyDriver(response=json.dumps(valid_deliverable_dict))
        node = ImplementationNode(spy)
        retry_ctx = TaskRetryContext(
            task_id=sample_task.id,
            error_message="SyntaxError on line 12",
            retry_count=0,
            previous_deliverable=None,
        )
        deliverable, meta = await node.implement(sample_task, retry_context=retry_ctx)
        assert "RETRY ATTEMPT 1" in spy.last_prompt
        assert "SyntaxError on line 12" in spy.last_prompt

    async def test_implement_raises_on_invalid_json(self, sample_task: TaskItem) -> None:
        driver = MockDriver(response="not json at all")
        node = ImplementationNode(driver)
        with pytest.raises(ImplementationError) as exc_info:
            await node.implement(sample_task)
        assert "Sanitization failed" in str(exc_info.value)
        assert exc_info.value.raw_response == "not json at all"

    async def test_implement_raises_on_invalid_schema(self, sample_task: TaskItem) -> None:
        driver = MockDriver(response=json.dumps({"wrong": "schema", "edits": "not_a_list"}))
        node = ImplementationNode(driver)
        with pytest.raises(ImplementationError) as exc_info:
            await node.implement(sample_task)
        assert "Deliverable validation failed" in str(exc_info.value)

    async def test_implement_returns_metadata(
        self, sample_task: TaskItem, valid_deliverable_dict: dict
    ) -> None:
        driver = MockDriver(response=json.dumps(valid_deliverable_dict))
        node = ImplementationNode(driver)
        _, meta = await node.implement(sample_task)
        assert meta.input_tokens > 0
        assert meta.model_name == "mock"

    async def test_prompt_contains_task_instruction(
        self, sample_task: TaskItem, valid_deliverable_dict: dict
    ) -> None:
        spy = SpyDriver(response=json.dumps(valid_deliverable_dict))
        node = ImplementationNode(spy)
        await node.implement(sample_task)
        assert sample_task.instruction in spy.last_prompt
        assert sample_task.id in spy.last_prompt
        assert sample_task.description in spy.last_prompt

    async def test_system_prompt_references_deliverable_schema(
        self, sample_task: TaskItem, valid_deliverable_dict: dict
    ) -> None:
        spy = SpyDriver(response=json.dumps(valid_deliverable_dict))
        node = ImplementationNode(spy)
        await node.implement(sample_task)
        assert "TaskDeliverable" in spy.last_system or "task_id" in spy.last_system

    async def test_task_id_injected_if_missing_from_response(
        self, sample_task: TaskItem, valid_deliverable_dict: dict
    ) -> None:
        data = dict(valid_deliverable_dict)
        del data["task_id"]
        driver = MockDriver(response=json.dumps(data))
        node = ImplementationNode(driver)
        deliverable, _ = await node.implement(sample_task)
        assert deliverable.task_id == sample_task.id
