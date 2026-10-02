"""Tests for Plan Executor."""
from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from hermetic.compute.driver import NodeExecutionMetadata
from hermetic.compute.implementation_node import ImplementationError
from hermetic.control.executor import (
    ExecutionResult,
    TaskExecutionError,
    _validate_worktree,
    execute_plan,
)
from hermetic.schemas.deliverable import StructuredFileEdit, TaskDeliverable
from hermetic.schemas.plan import ImplementationPlan, TaskBatch, TaskItem


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal real git repository with a committed target.py."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True, capture_output=True)
    target = repo / "target.py"
    target.write_text("# placeholder\ndef hello(): pass\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)
    return repo


class MockImplementationNode:
    """Standalone duck-typed test double for ImplementationNode.

    Does not inherit from ImplementationNode — execute_plan calls .implement() via
    duck typing, not isinstance, so no parent class is required.
    """

    def __init__(
        self,
        deliverables_queue: list[TaskDeliverable | Exception] | None = None,
        deliverables_by_task: dict[str, TaskDeliverable | Exception] | None = None,
    ) -> None:
        self._queue = list(deliverables_queue) if deliverables_queue else []
        self._by_task = deliverables_by_task or {}
        self._call_count = 0

    async def implement(self, task, retry_context=None):
        if task.id in self._by_task:
            item = self._by_task[task.id]
        elif self._queue:
            item = self._queue[self._call_count % len(self._queue)]
            self._call_count += 1
        else:
            raise ValueError(f"No mock deliverable for task {task.id}")

        if isinstance(item, Exception):
            raise ImplementationError(str(item), raw_response="")
        meta = NodeExecutionMetadata(
            input_tokens=10, output_tokens=5, latency_ms=1.0, model_name="mock"
        )
        return item, meta


class TestExecutor:
    async def test_execute_plan_single_batch_single_task(self, git_repo: Path) -> None:
        task = TaskItem(id="task-1", description="edit", instruction="edit", dependencies=[])
        plan = ImplementationPlan(
            plan_id="p1",
            issue_id="GH-1",
            batches=[TaskBatch(batch_id="b1", tasks=[task])],
        )
        edit = StructuredFileEdit(
            file_path="target.py",
            search_string="# placeholder",
            replacement_string="# edited",
            expected_occurrences=1,
        )
        deliverable = TaskDeliverable(task_id="task-1", edits=[edit], explanation="edited")
        mock_node = MockImplementationNode([deliverable])

        result = await execute_plan(plan, git_repo, "main", mock_node)
        assert len(result.deliverables) == 1
        assert result.deliverables[0].task_id == "task-1"
        assert (git_repo / "target.py").read_text(encoding="utf-8").startswith("# edited")

    async def test_execute_plan_sequential_batches(self, git_repo: Path) -> None:
        t1 = TaskItem(id="task-1", description="b1", instruction="b1", dependencies=[])
        t2 = TaskItem(id="task-2", description="b2", instruction="b2", dependencies=[])
        plan = ImplementationPlan(
            plan_id="p2",
            issue_id="GH-1",
            batches=[
                TaskBatch(batch_id="b1", tasks=[t1]),
                TaskBatch(batch_id="b2", tasks=[t2]),
            ],
        )
        d1 = TaskDeliverable(
            task_id="task-1",
            edits=[
                StructuredFileEdit(
                    file_path="target.py",
                    search_string="# placeholder",
                    replacement_string="# batch1",
                    expected_occurrences=1,
                )
            ],
        )
        d2 = TaskDeliverable(
            task_id="task-2",
            edits=[
                StructuredFileEdit(
                    file_path="target.py",
                    search_string="# batch1",
                    replacement_string="# batch2",
                    expected_occurrences=1,
                )
            ],
        )
        mock_node = MockImplementationNode(deliverables_by_task={"task-1": d1, "task-2": d2})
        result = await execute_plan(plan, git_repo, "main", mock_node)
        assert len(result.deliverables) == 2
        assert (git_repo / "target.py").read_text(encoding="utf-8").startswith("# batch2")

    async def test_execute_plan_retry_on_worktree_error(self, git_repo: Path) -> None:
        task = TaskItem(id="retry-task", description="retry", instruction="retry", dependencies=[])
        plan = ImplementationPlan(
            plan_id="p3",
            issue_id="GH-1",
            batches=[TaskBatch(batch_id="b1", tasks=[task])],
        )
        bad_edit = StructuredFileEdit(
            file_path="target.py",
            search_string="DOES_NOT_EXIST",
            replacement_string="failed",
            expected_occurrences=1,
        )
        good_edit = StructuredFileEdit(
            file_path="target.py",
            search_string="# placeholder",
            replacement_string="# fixed",
            expected_occurrences=1,
        )
        bad_d = TaskDeliverable(task_id="retry-task", edits=[bad_edit])
        good_d = TaskDeliverable(task_id="retry-task", edits=[good_edit])

        mock_node = MockImplementationNode(deliverables_queue=[bad_d, good_d])
        result = await execute_plan(plan, git_repo, "main", mock_node, max_retries=2)
        assert len(result.deliverables) == 1
        assert (git_repo / "target.py").read_text(encoding="utf-8").startswith("# fixed")

    async def test_execute_plan_hard_stop_on_exhausted_retries(self, git_repo: Path) -> None:
        task = TaskItem(id="bad-task", description="bad", instruction="bad", dependencies=[])
        plan = ImplementationPlan(
            plan_id="p4",
            issue_id="GH-1",
            batches=[TaskBatch(batch_id="b1", tasks=[task])],
        )
        bad_edit = StructuredFileEdit(
            file_path="target.py",
            search_string="DOES_NOT_EXIST",
            replacement_string="failed",
            expected_occurrences=1,
        )
        bad_d = TaskDeliverable(task_id="bad-task", edits=[bad_edit])
        mock_node = MockImplementationNode(deliverables_queue=[bad_d])
        with pytest.raises(TaskExecutionError) as exc_info:
            await execute_plan(plan, git_repo, "main", mock_node, max_retries=0)
        assert exc_info.value.task_id == "bad-task"

    async def test_execute_plan_token_aggregation(self, git_repo: Path) -> None:
        t1 = TaskItem(id="t1", description="t1", instruction="t1", dependencies=[])
        t2 = TaskItem(id="t2", description="t2", instruction="t2", dependencies=[])
        plan = ImplementationPlan(
            plan_id="p5",
            issue_id="GH-1",
            batches=[
                TaskBatch(batch_id="b1", tasks=[t1]),
                TaskBatch(batch_id="b2", tasks=[t2]),
            ],
        )
        d1 = TaskDeliverable(
            task_id="t1",
            edits=[
                StructuredFileEdit(
                    file_path="target.py",
                    search_string="# placeholder",
                    replacement_string="# step1",
                    expected_occurrences=1,
                )
            ],
        )
        d2 = TaskDeliverable(
            task_id="t2",
            edits=[
                StructuredFileEdit(
                    file_path="target.py",
                    search_string="# step1",
                    replacement_string="# step2",
                    expected_occurrences=1,
                )
            ],
        )
        mock_node = MockImplementationNode(deliverables_by_task={"t1": d1, "t2": d2})
        result = await execute_plan(plan, git_repo, "main", mock_node)
        assert result.total_input_tokens == 20
        assert result.total_output_tokens == 10

    async def test_execute_plan_parallel_tasks_in_same_batch(self, git_repo: Path) -> None:
        (git_repo / "file_a.py").write_text("a = 1\n", encoding="utf-8")
        (git_repo / "file_b.py").write_text("b = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "add a and b"], check=True, capture_output=True)

        t1 = TaskItem(id="task-a", description="edit a", instruction="edit a", dependencies=[])
        t2 = TaskItem(id="task-b", description="edit b", instruction="edit b", dependencies=[])
        plan = ImplementationPlan(
            plan_id="p6",
            issue_id="GH-1",
            batches=[TaskBatch(batch_id="b1", tasks=[t1, t2])],
        )
        d1 = TaskDeliverable(
            task_id="task-a",
            edits=[
                StructuredFileEdit(
                    file_path="file_a.py",
                    search_string="1",
                    replacement_string="2",
                    expected_occurrences=1,
                )
            ],
        )
        d2 = TaskDeliverable(
            task_id="task-b",
            edits=[
                StructuredFileEdit(
                    file_path="file_b.py",
                    search_string="1",
                    replacement_string="2",
                    expected_occurrences=1,
                )
            ],
        )
        mock_node = MockImplementationNode(deliverables_by_task={"task-a": d1, "task-b": d2})
        result = await execute_plan(plan, git_repo, "main", mock_node)
        assert len(result.deliverables) == 2
        assert (git_repo / "file_a.py").read_text(encoding="utf-8") == "a = 2\n"
        assert (git_repo / "file_b.py").read_text(encoding="utf-8") == "b = 2\n"

    def test_validate_worktree_skips_ruff_when_not_found(self, tmp_path: Path) -> None:
        with patch("shutil.which", return_value=None):
            assert _validate_worktree(tmp_path) is None

    async def test_task_execution_error_carries_task_id(self, git_repo: Path) -> None:
        task = TaskItem(id="failing-task", description="fail", instruction="fail", dependencies=[])
        plan = ImplementationPlan(
            plan_id="plan-err",
            issue_id="GH-1",
            batches=[TaskBatch(batch_id="b1", tasks=[task])],
        )
        bad_edit = StructuredFileEdit(
            file_path="target.py",
            search_string="NONEXISTENT",
            replacement_string="bar",
            expected_occurrences=1,
        )
        mock_node = MockImplementationNode([TaskDeliverable(task_id="failing-task", edits=[bad_edit])])
        with pytest.raises(TaskExecutionError) as exc_info:
            await execute_plan(plan, git_repo, "main", mock_node, max_retries=1)
        assert exc_info.value.task_id == "failing-task"

    async def test_execute_plan_empty_edits_treated_as_failure(self, git_repo: Path) -> None:
        task = TaskItem(id="empty-task", description="empty", instruction="empty", dependencies=[])
        plan = ImplementationPlan(
            plan_id="plan-empty",
            issue_id="GH-1",
            batches=[TaskBatch(batch_id="b1", tasks=[task])],
        )
        mock_node = MockImplementationNode([TaskDeliverable(task_id="empty-task", edits=[])])
        with pytest.raises(TaskExecutionError) as exc_info:
            await execute_plan(plan, git_repo, "main", mock_node, max_retries=0)
        assert exc_info.value.task_id == "empty-task"
        assert "Nothing to commit" in exc_info.value.message
