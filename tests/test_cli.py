"""Tests for CLI commands: plan, review, approve."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from hermetic.cli.app import app
from hermetic.client.github import GitHubIssue
from hermetic.compute.driver import NodeExecutionMetadata
from hermetic.control.executor import ExecutionResult, TaskExecutionError
from hermetic.control.state_machine import StateMachine
from hermetic.schemas.context import CodeSnippet, IssueContext
from hermetic.schemas.deliverable import TaskDeliverable
from hermetic.schemas.plan import ImplementationPlan, TaskBatch, TaskItem
from hermetic.schemas.review import ReviewFeedback
from hermetic.schemas.run import RunStatus


runner = CliRunner()


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "fake_repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


@pytest.fixture
def sample_plan() -> ImplementationPlan:
    return ImplementationPlan(
        plan_id="plan-cli-1",
        issue_id="GH-42",
        batches=[
            TaskBatch(
                batch_id="batch-1",
                description="Setup batch",
                tasks=[
                    TaskItem(
                        id="task-1",
                        description="Initial task",
                        instruction="Do the initial work",
                        dependencies=[],
                    )
                ],
            )
        ],
    )


@pytest.fixture
def sample_issue() -> GitHubIssue:
    return GitHubIssue(
        owner="test-org",
        repo="test-repo",
        number=42,
        title="Implement Feature 42",
        body="Detailed issue body for 42.",
        url="https://github.com/test-org/test-repo/issues/42",
    )


@pytest.fixture
def sample_meta() -> NodeExecutionMetadata:
    return NodeExecutionMetadata(
        input_tokens=100,
        output_tokens=50,
        latency_ms=120.0,
        model_name="claude-sonnet-4-6",
    )


class TestCli:
    def test_plan_command_requires_issue_id(self) -> None:
        result = runner.invoke(app, ["plan"])
        assert result.exit_code != 0

    def test_plan_command_exit_on_missing_token(self, fake_repo: Path) -> None:
        result = runner.invoke(
            app,
            [
                "plan",
                "42",
                "--repo",
                str(fake_repo),
                "--owner",
                "test-org",
                "--github-repo",
                "test-repo",
            ],
            env={"GITHUB_TOKEN": ""},
        )
        assert result.exit_code == 1
        assert "GITHUB_TOKEN is required" in result.output

    def test_plan_command_full_happy_path(
        self,
        fake_repo: Path,
        sample_issue: GitHubIssue,
        sample_plan: ImplementationPlan,
        sample_meta: NodeExecutionMetadata,
    ) -> None:
        feedback = ReviewFeedback(approved=True, comments="Looks great!", suggested_changes=[])

        with (
            patch("hermetic.cli.app.GitHubClient") as mock_gh,
            patch("hermetic.cli.app.PlanningNode") as mock_planner,
            patch("hermetic.cli.app.CriticNode") as mock_critic,
        ):
            mock_gh.return_value.fetch_issue.return_value = sample_issue
            mock_planner.return_value.plan = AsyncMock(return_value=(sample_plan, sample_meta))
            mock_critic.return_value.evaluate = AsyncMock(return_value=(feedback, sample_meta))

            result = runner.invoke(
                app,
                [
                    "plan",
                    "42",
                    "--repo",
                    str(fake_repo),
                    "--owner",
                    "test-org",
                    "--github-repo",
                    "test-repo",
                    "--token",
                    "fake-token",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Plan Generated" in result.output
        assert "Run ID:" in result.output

        # Verify plan.html was created
        runs_dir = fake_repo / ".harness" / "runs"
        assert runs_dir.exists()
        run_subdirs = list(runs_dir.iterdir())
        assert len(run_subdirs) == 1
        html_file = run_subdirs[0] / "plan.html"
        assert html_file.exists()
        assert "plan-cli-1" in html_file.read_text(encoding="utf-8")

    def test_plan_command_no_critic_flag_skips_critic(
        self,
        fake_repo: Path,
        sample_issue: GitHubIssue,
        sample_plan: ImplementationPlan,
        sample_meta: NodeExecutionMetadata,
    ) -> None:
        with (
            patch("hermetic.cli.app.GitHubClient") as mock_gh,
            patch("hermetic.cli.app.PlanningNode") as mock_planner,
            patch("hermetic.cli.app.CriticNode") as mock_critic,
        ):
            mock_gh.return_value.fetch_issue.return_value = sample_issue
            mock_planner.return_value.plan = AsyncMock(return_value=(sample_plan, sample_meta))

            result = runner.invoke(
                app,
                [
                    "plan",
                    "42",
                    "--repo",
                    str(fake_repo),
                    "--owner",
                    "test-org",
                    "--github-repo",
                    "test-repo",
                    "--token",
                    "fake-token",
                    "--no-critic",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Plan Generated" in result.output
        assert mock_critic.call_count == 0

    def test_plan_command_files_flag_attaches_snippets(
        self,
        fake_repo: Path,
        sample_issue: GitHubIssue,
        sample_plan: ImplementationPlan,
        sample_meta: NodeExecutionMetadata,
    ) -> None:
        src_dir = fake_repo / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        code_file = src_dir / "foo.py"
        code_file.write_text("def foo(): return 42\n", encoding="utf-8")

        with (
            patch("hermetic.cli.app.GitHubClient") as mock_gh,
            patch("hermetic.cli.app.PlanningNode") as mock_planner,
            patch("hermetic.cli.app.CriticNode"),
        ):
            mock_gh.return_value.fetch_issue.return_value = sample_issue
            mock_planner.return_value.plan = AsyncMock(return_value=(sample_plan, sample_meta))

            result = runner.invoke(
                app,
                [
                    "plan",
                    "42",
                    "--repo",
                    str(fake_repo),
                    "--owner",
                    "test-org",
                    "--github-repo",
                    "test-repo",
                    "--token",
                    "fake-token",
                    "--no-critic",
                    "--files",
                    "src/foo.py",
                ],
            )

        assert result.exit_code == 0, result.output
        context_arg: IssueContext = mock_planner.return_value.plan.call_args[0][0]
        assert len(context_arg.snippets) == 1
        assert context_arg.snippets[0].file_path == "src/foo.py"
        assert "def foo(): return 42" in context_arg.snippets[0].content

    def test_plan_command_rejects_absolute_file_path(
        self,
        fake_repo: Path,
        sample_issue: GitHubIssue,
    ) -> None:
        with patch("hermetic.cli.app.GitHubClient") as mock_gh:
            mock_gh.return_value.fetch_issue.return_value = sample_issue

            result = runner.invoke(
                app,
                [
                    "plan",
                    "42",
                    "--repo",
                    str(fake_repo),
                    "--owner",
                    "test-org",
                    "--github-repo",
                    "test-repo",
                    "--token",
                    "fake-token",
                    "--files",
                    "/absolute/path/file.py",
                ],
            )

        assert result.exit_code != 0
        assert "Absolute paths are not allowed" in result.output

    def test_review_command_with_feedback_saves_new_version(
        self,
        fake_repo: Path,
        sample_plan: ImplementationPlan,
        sample_meta: NodeExecutionMetadata,
    ) -> None:
        db_path = fake_repo / ".harness" / "state.db"
        sm = StateMachine(db_path)
        context = IssueContext(
            issue_id="GH-42",
            title="Feature 42",
            description="Body",
        )
        run_id = asyncio.run(
            sm.create_run(
                issue_id="GH-42",
                repo_path=str(fake_repo),
                base_branch="main",
                context=context,
            )
        )
        asyncio.run(sm.save_plan(run_id, sample_plan))

        revised_plan = ImplementationPlan(
            plan_id="plan-cli-2",
            issue_id="GH-42",
            batches=sample_plan.batches,
        )

        with (
            patch("hermetic.cli.app.PlanningNode") as mock_planner,
            patch("hermetic.cli.app.CriticNode") as mock_critic,
        ):
            mock_planner.return_value.plan = AsyncMock(return_value=(revised_plan, sample_meta))
            mock_critic.return_value.evaluate = AsyncMock(
                return_value=(
                    ReviewFeedback(approved=True, comments="Revised looks good", suggested_changes=[]),
                    sample_meta,
                )
            )

            result = runner.invoke(
                app,
                ["review", run_id, "--repo", str(fake_repo)],
                input="Add integration tests\n",
            )

        assert result.exit_code == 0, result.output
        assert "Plan Revised" in result.output
        assert "New Version: 2" in result.output

        versions = asyncio.run(sm.list_plan_versions(run_id))
        assert versions == [1, 2]

        latest = asyncio.run(sm.get_latest_plan(run_id))
        assert latest is not None
        assert latest[1] == 2
        assert latest[0].plan_id == "plan-cli-2"

    def test_review_command_empty_feedback_exits_cleanly(
        self,
        fake_repo: Path,
        sample_plan: ImplementationPlan,
    ) -> None:
        db_path = fake_repo / ".harness" / "state.db"
        sm = StateMachine(db_path)
        context = IssueContext(
            issue_id="GH-42",
            title="Feature 42",
            description="Body",
        )
        run_id = asyncio.run(
            sm.create_run(
                issue_id="GH-42",
                repo_path=str(fake_repo),
                base_branch="main",
                context=context,
            )
        )
        asyncio.run(sm.save_plan(run_id, sample_plan))

        result = runner.invoke(
            app,
            ["review", run_id, "--repo", str(fake_repo)],
            input="\n",
        )
        assert result.exit_code == 0
        assert "No feedback provided. Exiting." in result.output

        versions = asyncio.run(sm.list_plan_versions(run_id))
        assert versions == [1]

    def test_approve_command_updates_status(
        self,
        fake_repo: Path,
        sample_plan: ImplementationPlan,
    ) -> None:
        db_path = fake_repo / ".harness" / "state.db"
        sm = StateMachine(db_path)
        context = IssueContext(
            issue_id="GH-42",
            title="Feature 42",
            description="Body",
        )
        run_id = asyncio.run(
            sm.create_run(
                issue_id="GH-42",
                repo_path=str(fake_repo),
                base_branch="main",
                context=context,
            )
        )
        asyncio.run(sm.save_plan(run_id, sample_plan))

        result = runner.invoke(
            app,
            ["approve", run_id, "--repo", str(fake_repo)],
            input="y\n",
        )
        assert result.exit_code == 0
        assert "approved" in result.output.lower()
        assert f"hermetic implement {run_id}" in result.output

        run = asyncio.run(sm.get_run(run_id))
        assert run is not None
        assert run.status == RunStatus.APPROVED.value

    def test_approve_command_aborts_on_n_response(
        self,
        fake_repo: Path,
        sample_plan: ImplementationPlan,
    ) -> None:
        db_path = fake_repo / ".harness" / "state.db"
        sm = StateMachine(db_path)
        context = IssueContext(
            issue_id="GH-42",
            title="Feature 42",
            description="Body",
        )
        run_id = asyncio.run(
            sm.create_run(
                issue_id="GH-42",
                repo_path=str(fake_repo),
                base_branch="main",
                context=context,
            )
        )
        asyncio.run(sm.save_plan(run_id, sample_plan))

        result = runner.invoke(
            app,
            ["approve", run_id, "--repo", str(fake_repo)],
            input="n\n",
        )
        assert result.exit_code == 0
        assert "aborted" in result.output.lower()

        run = asyncio.run(sm.get_run(run_id))
        assert run is not None
        assert run.status == RunStatus.PLANNING.value


@pytest.fixture
def approved_run(fake_repo: Path, sample_plan: ImplementationPlan) -> tuple[str, Path]:
    """Create an APPROVED run in the state DB. Returns (run_id, db_path)."""
    db_path = fake_repo / ".harness" / "state.db"
    sm = StateMachine(db_path)
    context = IssueContext(
        issue_id="GH-42",
        title="Feature 42",
        description="Body",
    )
    run_id = asyncio.run(
        sm.create_run(
            issue_id="GH-42",
            repo_path=str(fake_repo),
            base_branch="main",
            context=context,
        )
    )
    asyncio.run(sm.save_plan(run_id, sample_plan))
    asyncio.run(sm.update_run_status(run_id, RunStatus.APPROVED))
    return run_id, db_path


class TestImplementCommand:
    def test_implement_command_rejects_non_approved_run(
        self, fake_repo: Path, sample_plan: ImplementationPlan
    ) -> None:
        db_path = fake_repo / ".harness" / "state.db"
        sm = StateMachine(db_path)
        context = IssueContext(issue_id="GH-42", title="Feature 42", description="Body")
        run_id = asyncio.run(
            sm.create_run(
                issue_id="GH-42",
                repo_path=str(fake_repo),
                base_branch="main",
                context=context,
            )
        )
        asyncio.run(sm.save_plan(run_id, sample_plan))

        result = runner.invoke(app, ["implement", run_id, "--repo", str(fake_repo)])
        assert result.exit_code == 1
        assert "Cannot execute run in status 'planning'" in result.output

    def test_implement_command_rejects_unknown_run_id(self, fake_repo: Path) -> None:
        result = runner.invoke(
            app,
            ["implement", "00000000-0000-0000-0000-000000000000", "--repo", str(fake_repo)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_implement_command_happy_path(
        self, fake_repo: Path, approved_run: tuple[str, Path]
    ) -> None:
        run_id, _ = approved_run
        mock_result = ExecutionResult(
            deliverables=[TaskDeliverable(task_id="task-1", edits=[], explanation="done")],
            failed_tasks=[],
            total_input_tokens=100,
            total_output_tokens=50,
        )
        with patch("hermetic.cli.app.execute_plan", new=AsyncMock(return_value=mock_result)):
            result = runner.invoke(app, ["implement", run_id, "--repo", str(fake_repo)])

        assert result.exit_code == 0, result.output
        html_path = fake_repo / ".harness" / "runs" / run_id / "full_report.html"
        assert html_path.exists()
        assert "plan-cli-1" in html_path.read_text(encoding="utf-8")

    def test_implement_command_transitions_status_to_done(
        self, fake_repo: Path, approved_run: tuple[str, Path]
    ) -> None:
        run_id, db_path = approved_run
        mock_result = ExecutionResult(
            deliverables=[TaskDeliverable(task_id="task-1", edits=[], explanation="done")],
            failed_tasks=[],
            total_input_tokens=100,
            total_output_tokens=50,
        )
        with patch("hermetic.cli.app.execute_plan", new=AsyncMock(return_value=mock_result)):
            result = runner.invoke(app, ["implement", run_id, "--repo", str(fake_repo)])

        assert result.exit_code == 0
        sm = StateMachine(db_path)
        run = asyncio.run(sm.get_run(run_id))
        assert run is not None
        assert run.status == RunStatus.DONE.value

    def test_implement_command_transitions_to_failed_on_error(
        self, fake_repo: Path, approved_run: tuple[str, Path]
    ) -> None:
        run_id, db_path = approved_run
        with patch(
            "hermetic.cli.app.execute_plan",
            new=AsyncMock(side_effect=TaskExecutionError("task-1", "oops")),
        ):
            result = runner.invoke(app, ["implement", run_id, "--repo", str(fake_repo)])

        assert result.exit_code == 1
        assert "Execution Failed" in result.output
        sm = StateMachine(db_path)
        run = asyncio.run(sm.get_run(run_id))
        assert run is not None
        assert run.status == RunStatus.FAILED.value

    def test_implement_command_prints_report_path(
        self, fake_repo: Path, approved_run: tuple[str, Path]
    ) -> None:
        run_id, _ = approved_run
        mock_result = ExecutionResult(
            deliverables=[TaskDeliverable(task_id="task-1", edits=[], explanation="done")],
            failed_tasks=[],
            total_input_tokens=100,
            total_output_tokens=50,
        )
        with patch("hermetic.cli.app.execute_plan", new=AsyncMock(return_value=mock_result)):
            result = runner.invoke(app, ["implement", run_id, "--repo", str(fake_repo)])

        assert result.exit_code == 0
        assert "full_report.html" in result.output

    def test_implement_command_dry_run_flag(
        self, fake_repo: Path, approved_run: tuple[str, Path]
    ) -> None:
        run_id, db_path = approved_run
        with patch("hermetic.cli.app.execute_plan", new=AsyncMock()) as mock_execute:
            result = runner.invoke(
                app, ["implement", run_id, "--repo", str(fake_repo), "--dry-run"]
            )

        assert result.exit_code == 0
        assert mock_execute.call_count == 0
        assert "Dry run" in result.output
        # Run remains approved
        sm = StateMachine(db_path)
        run = asyncio.run(sm.get_run(run_id))
        assert run is not None
        assert run.status == RunStatus.APPROVED.value

