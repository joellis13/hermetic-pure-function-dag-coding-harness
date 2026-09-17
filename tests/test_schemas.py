"""Tests for hermetic.schemas — Pydantic v2 contracts."""
import pytest
from pydantic import ValidationError

from hermetic.schemas import (
    CodeSnippet, ExternalDoc, IssueContext,
    TaskItem, TaskBatch, PlanIterationContext, ImplementationPlan,
    StructuredFileEdit, TaskDeliverable, TaskRetryContext, FullImplementationReport,
    ResearchQuery, ResearchResult,
    ReviewFeedback,
)


# ---------------------------------------------------------------------------
# context.py
# ---------------------------------------------------------------------------

class TestCodeSnippet:
    def test_happy_path(self):
        s = CodeSnippet(file_path="src/foo.py", content="x = 1", start_line=1, end_line=3)
        assert s.file_path == "src/foo.py"
        assert s.line_count == 3

    def test_frozen(self):
        s = CodeSnippet(file_path="src/foo.py", content="x = 1", start_line=1, end_line=1)
        with pytest.raises(Exception):  # ValidationError or TypeError
            s.file_path = "other.py"  # type: ignore[misc]

    def test_start_line_ge_1(self):
        with pytest.raises(ValidationError):
            CodeSnippet(file_path="f.py", content="x", start_line=0, end_line=1)

    def test_round_trip(self):
        s = CodeSnippet(file_path="src/foo.py", content="x = 1", start_line=10, end_line=20)
        assert CodeSnippet.model_validate_json(s.model_dump_json()) == s

    def test_end_line_lt_start_line_raises(self):
        with pytest.raises(ValidationError):
            CodeSnippet(file_path="f.py", content="x", start_line=10, end_line=5)


class TestExternalDoc:
    def test_happy_path(self):
        doc = ExternalDoc(url="https://docs.example.com", content="# Docs")
        assert doc.url == "https://docs.example.com"
        assert doc.title is None

    def test_with_title(self):
        doc = ExternalDoc(url="https://docs.example.com", content="# Docs", title="Example Docs")
        assert doc.title == "Example Docs"

    def test_round_trip(self):
        doc = ExternalDoc(url="https://docs.example.com", content="# Docs", title="Title")
        assert ExternalDoc.model_validate_json(doc.model_dump_json()) == doc


class TestIssueContext:
    def test_minimal_construction(self):
        ctx = IssueContext(issue_id="GH-1", title="Bug", description="It broke")
        assert ctx.snippets == []
        assert ctx.docs == []

    def test_with_snippets(self):
        snip = CodeSnippet(file_path="f.py", content="x", start_line=1, end_line=1)
        ctx = IssueContext(issue_id="GH-2", title="T", description="D", snippets=[snip])
        assert len(ctx.snippets) == 1

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            IssueContext(title="No ID")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# plan.py
# ---------------------------------------------------------------------------

class TestTaskItem:
    def test_auto_id(self):
        t = TaskItem(description="Do X", instruction="Write X")
        assert isinstance(t.id, str) and len(t.id) > 0

    def test_explicit_id(self):
        t = TaskItem(id="task-001", description="Do X", instruction="Write X")
        assert t.id == "task-001"

    def test_dependencies_default_empty(self):
        t = TaskItem(description="D", instruction="I")
        assert t.dependencies == []

    def test_round_trip(self):
        t = TaskItem(id="t1", description="D", instruction="I", dependencies=["t0"])
        assert TaskItem.model_validate_json(t.model_dump_json()) == t


class TestTaskBatch:
    def test_requires_at_least_one_task(self):
        with pytest.raises(ValidationError):
            TaskBatch(tasks=[])

    def test_happy_path(self):
        t = TaskItem(description="D", instruction="I")
        b = TaskBatch(tasks=[t])
        assert len(b.tasks) == 1


class TestImplementationPlan:
    def _make_plan(self) -> ImplementationPlan:
        t = TaskItem(description="D", instruction="I")
        b = TaskBatch(tasks=[t])
        return ImplementationPlan(issue_id="GH-1", batches=[b])

    def test_auto_plan_id(self):
        plan = self._make_plan()
        assert isinstance(plan.plan_id, str) and len(plan.plan_id) > 0

    def test_requires_batches(self):
        with pytest.raises(ValidationError):
            ImplementationPlan(issue_id="GH-1", batches=[])

    def test_round_trip(self):
        plan = self._make_plan()
        assert ImplementationPlan.model_validate_json(plan.model_dump_json()) == plan


class TestPlanIterationContext:
    def test_default_values(self):
        ctx = PlanIterationContext()
        assert ctx.iteration == 0
        assert ctx.feedback == ""

    def test_custom_values(self):
        ctx = PlanIterationContext(iteration=2, feedback="Add more error handling")
        assert ctx.iteration == 2
        assert ctx.feedback == "Add more error handling"

    def test_negative_iteration_invalid(self):
        with pytest.raises(ValidationError):
            PlanIterationContext(iteration=-1)


# ---------------------------------------------------------------------------
# deliverable.py
# ---------------------------------------------------------------------------

class TestStructuredFileEdit:
    def test_default_expected_occurrences(self):
        e = StructuredFileEdit(file_path="f.py", search_string="old", replacement_string="new")
        assert e.expected_occurrences == 1

    def test_zero_occurrences_invalid(self):
        with pytest.raises(ValidationError):
            StructuredFileEdit(file_path="f.py", search_string="x", replacement_string="y", expected_occurrences=0)


class TestTaskDeliverable:
    def test_happy_path(self):
        deliv = TaskDeliverable(task_id="t1")
        assert deliv.edits == []
        assert deliv.explanation == ""

    def test_round_trip(self):
        edit = StructuredFileEdit(file_path="f.py", search_string="x", replacement_string="y")
        deliv = TaskDeliverable(task_id="t1", edits=[edit], explanation="Fixed bug")
        assert TaskDeliverable.model_validate_json(deliv.model_dump_json()) == deliv


class TestTaskRetryContext:
    def test_retry_count_cap(self):
        with pytest.raises(ValidationError):
            TaskRetryContext(task_id="t1", error_message="err", retry_count=4)

    def test_valid_retry(self):
        r = TaskRetryContext(task_id="t1", error_message="err", retry_count=2)
        assert r.previous_deliverable is None


class TestFullImplementationReport:
    def test_happy_path(self):
        rep = FullImplementationReport(plan_id="p1")
        assert rep.deliverables == []
        assert rep.failed_tasks == []
        assert rep.summary == ""
        assert rep.total_input_tokens == 0
        assert rep.total_output_tokens == 0

    def test_round_trip(self):
        edit = StructuredFileEdit(file_path="f.py", search_string="x", replacement_string="y")
        deliv = TaskDeliverable(task_id="t1", edits=[edit])
        rep = FullImplementationReport(
            plan_id="p1",
            deliverables=[deliv],
            failed_tasks=["t2"],
            summary="All done except t2",
            total_input_tokens=1000,
            total_output_tokens=500,
        )
        assert FullImplementationReport.model_validate_json(rep.model_dump_json()) == rep


# ---------------------------------------------------------------------------
# research.py & review.py
# ---------------------------------------------------------------------------

class TestResearchSchemas:
    def test_research_query(self):
        q = ResearchQuery(query="find login", purpose="need auth code")
        assert q.read_files == []
        assert q.search_regex is None

    def test_research_result_round_trip(self):
        r = ResearchResult(query="find login", findings="def login(): ...")
        assert ResearchResult.model_validate_json(r.model_dump_json()) == r


class TestReviewFeedback:
    def test_approved(self):
        fb = ReviewFeedback(approved=True)
        assert fb.suggested_changes == []

    def test_rejected_with_changes(self):
        edit = StructuredFileEdit(file_path="f.py", search_string="a", replacement_string="b")
        fb = ReviewFeedback(approved=False, comments="Needs fix", suggested_changes=[edit])
        assert not fb.approved
        assert len(fb.suggested_changes) == 1
