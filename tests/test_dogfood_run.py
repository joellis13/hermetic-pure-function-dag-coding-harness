"""Dogfooding end-to-end test: full pipeline on the harness codebase itself."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from hermetic.compute.critic import CriticNode
from hermetic.compute.driver import AntigravityDriver
from hermetic.compute.implementation_node import ImplementationNode
from hermetic.compute.planning_node import PlanningNode
from hermetic.control.executor import execute_plan
from hermetic.control.state_machine import StateMachine
from hermetic.data.etl.assembler import ContextAssembler
from hermetic.data.renderer import render_report_html, write_html
from hermetic.schemas.deliverable import FullImplementationReport
from hermetic.schemas.plan import ImplementationPlan
from hermetic.schemas.run import RunStatus


live = pytest.mark.skipif(
    not os.getenv("HERMETIC_RUN_LIVE_TESTS"),
    reason="Set HERMETIC_RUN_LIVE_TESTS=1 to run the dogfooding end-to-end test",
)


class TestDogfoodRun:
    @live
    async def test_dogfood_full_pipeline(self, tmp_path: Path) -> None:
        """
        Full end-to-end dogfooding run.
        Builds a plan for 'add list-runs CLI command', executes it,
        verifies full_report.html is produced, and checks git log for hermetic commits.
        """
        repo_root = Path(__file__).resolve().parent.parent
        assembler = ContextAssembler(repo_root=repo_root)

        description = (
            "Add a new `hermetic list-runs` CLI command to the harness that queries "
            "the SQLite state database and displays all run IDs with their status, "
            "issue_id, and created_at timestamp in a Rich table.\n\n"
            "Requirements:\n"
            "1. Add `list_runs()` async method to `StateMachine` returning list of `RunState`.\n"
            "2. Add `list_runs_command` to `cli/app.py` using `@app.command(name='list-runs')`.\n"
            "3. Display results with Rich `Table` (columns: Run ID, Status, Issue ID, Created At).\n"
            "4. If no runs exist, print an informational message.\n"
        )

        context, _ = assembler.assemble(
            issue_id="DOGFOOD-1",
            title="Add list-runs CLI command",
            description=description,
            file_paths=[
                "src/hermetic/cli/app.py",
                "src/hermetic/control/state_machine.py",
            ],
            doc_urls_and_content=[],
        )

        planner_model = os.getenv("HERMETIC_LIVE_MODEL", "gemini-3-8-flash")
        impl_model = os.getenv("HERMETIC_IMPL_MODEL", "gemini-3-8-flash")

        # 1. Planning
        planner = PlanningNode(AntigravityDriver(planner_model))
        plan, plan_meta = await planner.plan(context)
        assert isinstance(plan, ImplementationPlan)
        assert len(plan.batches) >= 1

        # 2. Critic evaluation
        critic = CriticNode(planner_model, lambda m: AntigravityDriver(m))
        feedback, critic_meta = await critic.evaluate(plan, context)
        assert isinstance(feedback.approved, bool)

        # 3. State machine setup
        sm = StateMachine(tmp_path / "state.db")
        run_id = await sm.create_run(
            issue_id="DOGFOOD-1",
            repo_path=str(repo_root),
            base_branch="main",
            context=context,
        )
        await sm.save_plan(run_id, plan)
        await sm.update_run_status(run_id, RunStatus.APPROVED)

        # 4. Execution
        impl_node = ImplementationNode(AntigravityDriver(impl_model))
        result = await execute_plan(
            plan, repo_root, "main", impl_node, max_retries=3
        )

        assert result.failed_tasks == [], f"Failed tasks: {result.failed_tasks}"
        assert len(result.deliverables) >= 1

        # 5. Save and render report
        report = FullImplementationReport(
            plan_id=plan.plan_id,
            deliverables=result.deliverables,
            failed_tasks=result.failed_tasks,
            total_input_tokens=result.total_input_tokens,
            total_output_tokens=result.total_output_tokens,
            summary="Dogfood run complete — list-runs command added.",
        )
        await sm.save_report(run_id, report)
        await sm.update_run_status(run_id, RunStatus.DONE)

        html = render_report_html(report)
        html_path = tmp_path / "full_report.html"
        write_html(html, html_path)
        assert html_path.exists()
        assert "DOGFOOD-1" in html_path.read_text(encoding="utf-8")

        # 6. Verify git commits
        git_result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert "hermetic:" in git_result.stdout, (
            f"Expected hermetic commit in git log. Got:\n{git_result.stdout}"
        )
