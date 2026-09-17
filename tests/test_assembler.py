"""Tests for Context Assembler and Token Budget enforcement."""
from __future__ import annotations

from pathlib import Path

import pytest

from hermetic.data.etl import (
    PLANNING_BUDGET,
    ContextAssembler,
    TokenBudgetExceeded,
    estimate_tokens,
)


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A temporary directory with a few files of known content."""
    (tmp_path / "small.py").write_text("x = 1\n", encoding="utf-8")  # 6 chars -> 1 token
    (tmp_path / "medium.py").write_text("y = " + "A" * 400 + "\n", encoding="utf-8")  # 405 chars -> 101 tokens
    (tmp_path / "large.py").write_text("z = " + "B" * 4000 + "\n", encoding="utf-8")  # 4005 chars -> 1001 tokens
    return tmp_path


class TestEstimateTokens:
    def test_empty_string_returns_zero(self) -> None:
        assert estimate_tokens("") == 0

    def test_four_chars_returns_one(self) -> None:
        assert estimate_tokens("abcd") == 1

    def test_eight_chars_returns_two(self) -> None:
        assert estimate_tokens("abcdefgh") == 2

    def test_known_string(self) -> None:
        text = "a" * 100
        assert estimate_tokens(text) == 25


class TestContextAssemblerHappyPath:
    def test_minimal_context_no_files_no_docs(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root)
        context, warning = assembler.assemble(
            issue_id="ISSUE-1",
            title="Fix bug",
            description="Short description",
            file_paths=[],
            doc_urls_and_content=[],
        )
        assert context.issue_id == "ISSUE-1"
        assert context.title == "Fix bug"
        assert context.description == "Short description"
        assert context.snippets == []
        assert context.docs == []
        assert warning is None

    def test_reads_file_and_creates_snippet(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root)
        snippet = assembler.read_file_snippet("small.py")
        assert snippet.file_path == "small.py"
        assert snippet.content == "x = 1\n"
        assert snippet.start_line == 1
        assert snippet.end_line == 1

    def test_snippet_start_line_is_1(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root)
        snippet = assembler.read_file_snippet("small.py")
        assert snippet.start_line == 1

    def test_snippet_end_line_matches_line_count(self, repo_root: Path) -> None:
        (repo_root / "multi.py").write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
        assembler = ContextAssembler(repo_root=repo_root)
        snippet = assembler.read_file_snippet("multi.py")
        assert snippet.start_line == 1
        assert snippet.end_line == 3
        assert snippet.line_count == 3

    def test_multiple_files_assembled(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root)
        context, warning = assembler.assemble(
            issue_id="ISSUE-2",
            title="Two files",
            description="Assemble two files",
            file_paths=["small.py", "medium.py"],
            doc_urls_and_content=[],
        )
        assert len(context.snippets) == 2
        assert context.snippets[0].file_path == "small.py"
        assert context.snippets[1].file_path == "medium.py"
        assert warning is None

    def test_doc_added_to_context(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root)
        context, warning = assembler.assemble(
            issue_id="ISSUE-3",
            title="Doc test",
            description="Includes doc",
            file_paths=[],
            doc_urls_and_content=[("https://example.com/doc", "Doc content", "Doc Title")],
        )
        assert len(context.docs) == 1
        assert context.docs[0].url == "https://example.com/doc"
        assert context.docs[0].content == "Doc content"
        assert context.docs[0].title == "Doc Title"
        assert warning is None

    def test_no_budget_exceeded_returns_none_warning(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root, token_budget=PLANNING_BUDGET)
        _, warning = assembler.assemble(
            issue_id="ISSUE-4",
            title="Budget ok",
            description="desc",
            file_paths=["small.py"],
            doc_urls_and_content=[],
        )
        assert warning is None


class TestTokenBudgetEnforcement:
    def test_oversized_file_is_skipped(self, repo_root: Path) -> None:
        # Budget allows description and small.py, but not large.py (~1001 tokens)
        assembler = ContextAssembler(repo_root=repo_root, token_budget=50)
        context, warning = assembler.assemble(
            issue_id="ISSUE-T1",
            title="Oversized",
            description="desc",
            file_paths=["small.py", "large.py"],
            doc_urls_and_content=[],
        )
        assert len(context.snippets) == 1
        assert context.snippets[0].file_path == "small.py"
        assert warning is not None
        assert "snippet:large.py" in warning.skipped_items

    def test_skipped_file_listed_in_budget_exceeded(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root, token_budget=10)
        _, warning = assembler.assemble(
            issue_id="ISSUE-T2",
            title="Skipped list",
            description="",
            file_paths=["medium.py"],
            doc_urls_and_content=[],
        )
        assert warning is not None
        assert warning.skipped_items == ["snippet:medium.py"]

    def test_partial_assembly_still_returns_context(self, repo_root: Path) -> None:
        # small.py (1 tok), large.py (1001 tok), small.py again
        # Budget = 10: small.py fits (1), large.py skipped (1001), second small.py fits (1)
        assembler = ContextAssembler(repo_root=repo_root, token_budget=10)
        context, warning = assembler.assemble(
            issue_id="ISSUE-T3",
            title="Partial",
            description="",
            file_paths=["small.py", "large.py", "small.py"],
            doc_urls_and_content=[],
        )
        assert len(context.snippets) == 2
        assert warning is not None
        assert warning.skipped_items == ["snippet:large.py"]

    def test_doc_skipped_when_budget_exhausted(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root, token_budget=5)
        # 1 token for desc, 1 for small.py -> 2 used, 3 left. Doc is 40 chars -> 10 tokens -> skipped
        context, warning = assembler.assemble(
            issue_id="ISSUE-T4",
            title="Doc skip",
            description="desc",
            file_paths=["small.py"],
            doc_urls_and_content=[("https://doc.com", "A" * 40, "Title")],
        )
        assert len(context.snippets) == 1
        assert len(context.docs) == 0
        assert warning is not None
        assert "doc:https://doc.com" in warning.skipped_items

    def test_description_tokens_count_against_budget(self, repo_root: Path) -> None:
        # 40 chars description = 10 tokens. Budget = 10. small.py needs 1 token -> skipped!
        assembler = ContextAssembler(repo_root=repo_root, token_budget=10)
        context, warning = assembler.assemble(
            issue_id="ISSUE-T5",
            title="Desc count",
            description="D" * 40,
            file_paths=["small.py"],
            doc_urls_and_content=[],
        )
        assert len(context.snippets) == 0
        assert warning is not None
        assert "snippet:small.py" in warning.skipped_items

    def test_budget_exceeded_has_correct_used_count(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root, token_budget=5)
        desc = "1234"  # 1 token
        # small.py has 6 chars -> 1 token. Used = 1 + 1 = 2
        context, warning = assembler.assemble(
            issue_id="ISSUE-T6",
            title="Used count",
            description=desc,
            file_paths=["small.py", "large.py"],
            doc_urls_and_content=[],
        )
        assert warning is not None
        assert warning.budget == 5
        assert warning.used == 2

    def test_zero_budget_skips_all_files(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root, token_budget=0)
        context, warning = assembler.assemble(
            issue_id="ISSUE-T7",
            title="Zero budget",
            description="Some description",  # 4 tokens
            file_paths=["small.py", "medium.py"],
            doc_urls_and_content=[("https://doc.com", "Content", None)],
        )
        assert len(context.snippets) == 0
        assert len(context.docs) == 0
        assert warning is not None
        assert len(warning.skipped_items) == 3
        assert warning.skipped_items == ["snippet:small.py", "snippet:medium.py", "doc:https://doc.com"]


class TestFileNotFound:
    def test_read_file_snippet_raises_on_missing_file(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root)
        with pytest.raises(FileNotFoundError, match="File not found: not_real.py"):
            assembler.read_file_snippet("not_real.py")

    def test_assemble_raises_file_not_found_on_missing_file(self, repo_root: Path) -> None:
        assembler = ContextAssembler(repo_root=repo_root)
        with pytest.raises(FileNotFoundError, match="File not found: missing.py"):
            assembler.assemble(
                issue_id="ISSUE-FNF",
                title="Missing",
                description="desc",
                file_paths=["small.py", "missing.py"],
                doc_urls_and_content=[],
            )
