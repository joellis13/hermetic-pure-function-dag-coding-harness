"""End-to-end integration tests for the planning workflow (no network, local SQLite)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermetic.compute.driver import MockDriver
from hermetic.compute.planning_node import PlanningNode
from hermetic.control.state_machine import StateMachine
from hermetic.schemas.context import CodeSnippet, IssueContext
from hermetic.schemas.plan import ImplementationPlan, PlanIterationContext, TaskBatch, TaskItem
from hermetic.schemas.run import RunStatus


@pytest.fixture
def sample_context() -> IssueContext:
    return IssueContext(
        issue_id="GH-100",
        title="Full Lifecycle Feature",
        description="Verify the entire planning cycle from creation to approval.",
        snippets=[
            CodeSnippet(
                file_path="src/service.py",
                content="class Service: pass\n",
                start_line=1,
                end_line=1,
            )
        ],
    )


def _make_plan_json(plan_id: str, issue_id: str, task_desc: str) -> str:
    return json.dumps(
        {
            "plan_id": plan_id,
            "issue_id": issue_id,
            "batches": [
                {
                    "batch_id": f"batch-{plan_id}",
                    "description": "Execution batch",
                    "tasks": [
                        {
                            "id": "task-1",
                            "description": task_desc,
                            "instruction": f"Execute: {task_desc}",
                            "dependencies": [],
                        }
                    ],
                }
            ],
        }
    )


class TestPlanningIntegration:
    async def test_plan_review_approve_cycle(
        self, tmp_path: Path, sample_context: IssueContext
    ) -> None:
        """
        create_run → plan v1 (MockDriver) → save → review with feedback → plan v2 → save → approve.
        Verifies:
        - 2 checkpoints persisted
        - get_context() round-trips correctly (snapshot preserved)
        - run status == 'approved' after approve step
        """
        db_path = tmp_path / "state.db"
        sm = StateMachine(db_path)

        # 1. Create run with context snapshot
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        run_id = await sm.create_run(
            issue_id=sample_context.issue_id,
            repo_path=str(repo_dir),
            base_branch="main",
            context=sample_context,
        )
        assert run_id is not None

        # Verify initial state
        initial_run = await sm.get_run(run_id)
        assert initial_run is not None
        assert initial_run.status == RunStatus.PLANNING.value

        # 2. Plan v1
        v1_json = _make_plan_json("plan-v1", sample_context.issue_id, "Task version 1")
        planner_v1 = PlanningNode(driver=MockDriver(response=v1_json))
        plan_v1, meta_v1 = await planner_v1.plan(sample_context)

        v1 = await sm.save_plan(run_id, plan_v1, feedback="")
        assert v1 == 1

        # 3. Review: re-hydrate context snapshot (offline, no network)
        rehydrated_context = await sm.get_context(run_id)
        assert rehydrated_context is not None
        assert rehydrated_context == sample_context

        # 4. Plan v2 with feedback
        feedback = "Add error handling and tests"
        iter_ctx = PlanIterationContext(iteration=v1, feedback=feedback)
        v2_json = _make_plan_json("plan-v2", sample_context.issue_id, "Task version 2 with error handling")
        planner_v2 = PlanningNode(driver=MockDriver(response=v2_json))
        plan_v2, meta_v2 = await planner_v2.plan(rehydrated_context, iteration=iter_ctx)

        v2 = await sm.save_plan(run_id, plan_v2, feedback=feedback)
        assert v2 == 2

        # 5. Verify 2 checkpoints persisted
        versions = await sm.list_plan_versions(run_id)
        assert versions == [1, 2]

        latest = await sm.get_latest_plan(run_id)
        assert latest is not None
        latest_plan, latest_version = latest
        assert latest_version == 2
        assert latest_plan.plan_id == "plan-v2"

        saved_v1 = await sm.get_plan_version(run_id, 1)
        assert saved_v1 is not None
        assert saved_v1.plan_id == "plan-v1"

        saved_feedback = await sm.get_plan_feedback(run_id, 2)
        assert saved_feedback == feedback

        # 6. Approve plan
        await sm.update_run_status(run_id, RunStatus.APPROVED)

        approved_run = await sm.get_run(run_id)
        assert approved_run is not None
        assert approved_run.status == RunStatus.APPROVED.value

        # Context snapshot is still preserved
        assert await sm.get_context(run_id) == sample_context
