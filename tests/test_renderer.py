"""Tests for the HTML Renderer."""
from __future__ import annotations

from pathlib import Path

import pytest

from hermetic.data.renderer import render_plan_html, render_report_html, write_html
from hermetic.schemas.context import IssueContext
from hermetic.schemas.deliverable import FullImplementationReport, StructuredFileEdit, TaskDeliverable
from hermetic.schemas.plan import ImplementationPlan, PlanIterationContext, TaskBatch, TaskItem


@pytest.fixture
def sample_plan() -> ImplementationPlan:
    return ImplementationPlan(
        plan_id="plan-123",
        issue_id="GH-42",
        batches=[
            TaskBatch(
                batch_id="batch-1",
                description="Core Setup",
                tasks=[
                    TaskItem(
                        id="task-init",
                        description="Initialize project structure",
                        instruction="Create directories and config",
                        dependencies=[],
                    ),
                    TaskItem(
                        id="task-db",
                        description="Setup database",
                        instruction="Configure SQLite",
                        dependencies=["task-init"],
                    ),
                ],
            )
        ],
        iteration_context=PlanIterationContext(iteration=0, feedback=""),
    )


@pytest.fixture
def sample_context() -> IssueContext:
    return IssueContext(
        issue_id="GH-42",
        title="Add database integration",
        description="We need SQLite integration for persistence.",
        snippets=[],
        docs=[],
    )


@pytest.fixture
def sample_report() -> FullImplementationReport:
    return FullImplementationReport(
        plan_id="plan-123",
        deliverables=[
            TaskDeliverable(
                task_id="task-init",
                edits=[
                    StructuredFileEdit(
                        file_path="src/main.py",
                        search_string="# todo",
                        replacement_string="import sqlite3",
                        expected_occurrences=1,
                    )
                ],
                explanation="Added sqlite import",
            )
        ],
        failed_tasks=["task-db"],
        summary="Completed 1/2 tasks",
        total_input_tokens=1500,
        total_output_tokens=350,
    )


class TestRenderPlanHtml:
    def test_returns_string(self, sample_plan: ImplementationPlan) -> None:
        html = render_plan_html(sample_plan)
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_plan_id(self, sample_plan: ImplementationPlan) -> None:
        html = render_plan_html(sample_plan)
        assert "plan-123" in html

    def test_contains_issue_id(self, sample_plan: ImplementationPlan) -> None:
        html = render_plan_html(sample_plan)
        assert "GH-42" in html

    def test_contains_batch_description(self, sample_plan: ImplementationPlan) -> None:
        html = render_plan_html(sample_plan)
        assert "Core Setup" in html

    def test_contains_task_description(self, sample_plan: ImplementationPlan) -> None:
        html = render_plan_html(sample_plan)
        assert "Initialize project structure" in html

    def test_contains_task_id(self, sample_plan: ImplementationPlan) -> None:
        html = render_plan_html(sample_plan)
        assert "task-init" in html

    def test_with_none_context_does_not_error(self, sample_plan: ImplementationPlan) -> None:
        html = render_plan_html(sample_plan, context=None)
        assert isinstance(html, str)

    def test_with_context_includes_context_details(
        self, sample_plan: ImplementationPlan, sample_context: IssueContext
    ) -> None:
        html = render_plan_html(sample_plan, context=sample_context)
        assert "Add database integration" in html
        assert "We need SQLite integration for persistence." in html

    def test_iteration_feedback_shown_when_iteration_gt_0(self) -> None:
        plan = ImplementationPlan(
            plan_id="plan-revised",
            issue_id="GH-99",
            batches=[
                TaskBatch(
                    description="Revision Batch",
                    tasks=[TaskItem(description="Fix lints", instruction="Run ruff")],
                )
            ],
            iteration_context=PlanIterationContext(iteration=1, feedback="Please add unit tests"),
        )
        html = render_plan_html(plan)
        assert "Please add unit tests" in html
        assert "Iteration 1 Feedback" in html

    def test_html_escaped_xss_attempt(self) -> None:
        plan = ImplementationPlan(
            plan_id="plan-xss",
            issue_id="GH-XSS",
            batches=[
                TaskBatch(
                    description="XSS Test",
                    tasks=[
                        TaskItem(
                            description="<script>alert(1)</script>",
                            instruction="<b>Bold</b>",
                        )
                    ],
                )
            ],
        )
        html = render_plan_html(plan)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


class TestRenderReportHtml:
    def test_returns_string(self, sample_report: FullImplementationReport) -> None:
        html = render_report_html(sample_report)
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_plan_id(self, sample_report: FullImplementationReport) -> None:
        html = render_report_html(sample_report)
        assert "plan-123" in html

    def test_contains_task_id_in_deliverable(self, sample_report: FullImplementationReport) -> None:
        html = render_report_html(sample_report)
        assert "task-init" in html

    def test_contains_explanation(self, sample_report: FullImplementationReport) -> None:
        html = render_report_html(sample_report)
        assert "Added sqlite import" in html

    def test_failed_tasks_listed(self, sample_report: FullImplementationReport) -> None:
        html = render_report_html(sample_report)
        assert "task-db" in html
        assert "Failed Tasks (1)" in html

    def test_token_counts_shown(self, sample_report: FullImplementationReport) -> None:
        html = render_report_html(sample_report)
        assert "1500" in html
        assert "350" in html

    def test_zero_deliverables_renders_cleanly(self) -> None:
        empty_report = FullImplementationReport(
            plan_id="plan-empty",
            deliverables=[],
            failed_tasks=[],
            summary="Nothing was run",
        )
        html = render_report_html(empty_report)
        assert "plan-empty" in html
        assert "No deliverables generated." in html


class TestWriteHtml:
    def test_writes_file_to_disk(self, tmp_path: Path) -> None:
        out_file = tmp_path / "output.html"
        content = "<html><body>Hello World</body></html>"
        write_html(content, out_file)
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8") == content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        out_file = tmp_path / "sub" / "nested" / "output.html"
        content = "<html><body>Deep Nested</body></html>"
        write_html(content, out_file)
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8") == content

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        out_file = tmp_path / "output.html"
        out_file.write_text("old content", encoding="utf-8")
        new_content = "new content"
        write_html(new_content, out_file)
        assert out_file.read_text(encoding="utf-8") == new_content
