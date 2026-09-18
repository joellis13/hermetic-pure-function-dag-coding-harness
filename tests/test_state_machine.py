"""Tests for StateMachine (aiosqlite persistence)."""
from __future__ import annotations

from pathlib import Path
import uuid

import pytest

from hermetic.control.state_machine import RunState, StateMachine
from hermetic.schemas.context import CodeSnippet, IssueContext
from hermetic.schemas.plan import ImplementationPlan, TaskBatch, TaskItem
from hermetic.schemas.run import RunStatus


@pytest.fixture
def sample_context() -> IssueContext:
    return IssueContext(
        issue_id="GH-42",
        title="Test Issue Title",
        description="Detailed description of the issue.",
        snippets=[
            CodeSnippet(
                file_path="src/main.py",
                content="def main(): pass",
                start_line=1,
                end_line=1,
            )
        ],
    )


@pytest.fixture
def sample_plan() -> ImplementationPlan:
    return ImplementationPlan(
        plan_id="plan-test-1",
        issue_id="GH-42",
        batches=[
            TaskBatch(
                batch_id="batch-1",
                description="Initial setup",
                tasks=[
                    TaskItem(
                        id="task-1",
                        description="Write scaffolding",
                        instruction="Create initial boilerplate",
                        dependencies=[],
                    )
                ],
            )
        ],
    )


class TestStateMachine:
    async def test_create_run_returns_uuid(
        self, tmp_path: Path, sample_context: IssueContext
    ) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-42",
            repo_path="/test/repo",
            base_branch="main",
            context=sample_context,
        )
        assert isinstance(run_id, str)
        parsed = uuid.UUID(run_id)
        assert str(parsed) == run_id

    async def test_get_run_returns_run_state(
        self, tmp_path: Path, sample_context: IssueContext
    ) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-42",
            repo_path="/test/repo",
            base_branch="main",
            context=sample_context,
        )
        run = await sm.get_run(run_id)
        assert run is not None
        assert isinstance(run, RunState)
        assert run.run_id == run_id
        assert run.issue_id == "GH-42"
        assert run.repo_path == "/test/repo"
        assert run.base_branch == "main"
        assert run.status == RunStatus.PLANNING.value
        assert run.context_json == sample_context.model_dump_json()
        assert run.created_at.endswith("Z")
        assert run.updated_at.endswith("Z")

    async def test_get_run_returns_none_for_missing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run = await sm.get_run("non-existent-run-id")
        assert run is None

    async def test_save_plan_first_version_is_one(
        self,
        tmp_path: Path,
        sample_context: IssueContext,
        sample_plan: ImplementationPlan,
    ) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-42",
            repo_path="/test/repo",
            base_branch="main",
            context=sample_context,
        )
        v1 = await sm.save_plan(run_id, sample_plan)
        assert v1 == 1

    async def test_save_plan_increments_version(
        self,
        tmp_path: Path,
        sample_context: IssueContext,
        sample_plan: ImplementationPlan,
    ) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-42",
            repo_path="/test/repo",
            base_branch="main",
            context=sample_context,
        )
        v1 = await sm.save_plan(run_id, sample_plan)
        v2 = await sm.save_plan(run_id, sample_plan, feedback="Revision 1")
        v3 = await sm.save_plan(run_id, sample_plan, feedback="Revision 2")
        assert v1 == 1
        assert v2 == 2
        assert v3 == 3

    async def test_get_latest_plan_returns_highest_version(
        self,
        tmp_path: Path,
        sample_context: IssueContext,
        sample_plan: ImplementationPlan,
    ) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-42",
            repo_path="/test/repo",
            base_branch="main",
            context=sample_context,
        )
        # Empty DB returns None
        empty = await sm.get_latest_plan(run_id)
        assert empty is None

        plan2 = ImplementationPlan(
            plan_id="plan-test-2",
            issue_id="GH-42",
            batches=sample_plan.batches,
        )
        await sm.save_plan(run_id, sample_plan)
        await sm.save_plan(run_id, plan2)

        latest = await sm.get_latest_plan(run_id)
        assert latest is not None
        plan_out, version_out = latest
        assert version_out == 2
        assert plan_out.plan_id == "plan-test-2"

    async def test_get_plan_version_returns_specific_version(
        self,
        tmp_path: Path,
        sample_context: IssueContext,
        sample_plan: ImplementationPlan,
    ) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-42",
            repo_path="/test/repo",
            base_branch="main",
            context=sample_context,
        )
        plan2 = ImplementationPlan(
            plan_id="plan-test-v2",
            issue_id="GH-42",
            batches=sample_plan.batches,
        )
        await sm.save_plan(run_id, sample_plan)
        await sm.save_plan(run_id, plan2)

        v1_plan = await sm.get_plan_version(run_id, 1)
        assert v1_plan is not None
        assert v1_plan.plan_id == "plan-test-1"

        v2_plan = await sm.get_plan_version(run_id, 2)
        assert v2_plan is not None
        assert v2_plan.plan_id == "plan-test-v2"

        v3_plan = await sm.get_plan_version(run_id, 3)
        assert v3_plan is None

    async def test_list_plan_versions_sorted(
        self,
        tmp_path: Path,
        sample_context: IssueContext,
        sample_plan: ImplementationPlan,
    ) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-42",
            repo_path="/test/repo",
            base_branch="main",
            context=sample_context,
        )
        await sm.save_plan(run_id, sample_plan)
        await sm.save_plan(run_id, sample_plan)
        await sm.save_plan(run_id, sample_plan)

        versions = await sm.list_plan_versions(run_id)
        assert versions == [1, 2, 3]

    async def test_update_run_status_persists(
        self, tmp_path: Path, sample_context: IssueContext
    ) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-42",
            repo_path="/test/repo",
            base_branch="main",
            context=sample_context,
        )
        await sm.update_run_status(run_id, RunStatus.APPROVED)
        run = await sm.get_run(run_id)
        assert run is not None
        assert run.status == RunStatus.APPROVED.value

    async def test_save_plan_preserves_feedback(
        self,
        tmp_path: Path,
        sample_context: IssueContext,
        sample_plan: ImplementationPlan,
    ) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-42",
            repo_path="/test/repo",
            base_branch="main",
            context=sample_context,
        )
        feedback_text = "Please add unit tests for edge cases"
        await sm.save_plan(run_id, sample_plan, feedback=feedback_text)
        saved_feedback = await sm.get_plan_feedback(run_id, 1)
        assert saved_feedback == feedback_text

    async def test_state_machine_creates_db_on_first_use(
        self, tmp_path: Path, sample_context: IssueContext
    ) -> None:
        deep_dir = tmp_path / "nested" / "subdir"
        db_path = deep_dir / "state.db"
        assert not db_path.exists()
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-1",
            repo_path="/repo",
            base_branch="main",
            context=sample_context,
        )
        assert db_path.exists()
        run = await sm.get_run(run_id)
        assert run is not None

    async def test_get_context_rehydrates_issue_context(
        self, tmp_path: Path, sample_context: IssueContext
    ) -> None:
        db_path = tmp_path / "test.db"
        sm = StateMachine(db_path)
        run_id = await sm.create_run(
            issue_id="GH-42",
            repo_path="/test/repo",
            base_branch="main",
            context=sample_context,
        )
        rehydrated = await sm.get_context(run_id)
        assert rehydrated is not None
        assert rehydrated == sample_context
        assert rehydrated.issue_id == sample_context.issue_id
        assert rehydrated.title == sample_context.title
        assert rehydrated.description == sample_context.description
        assert len(rehydrated.snippets) == len(sample_context.snippets)
        assert rehydrated.snippets[0].file_path == sample_context.snippets[0].file_path
