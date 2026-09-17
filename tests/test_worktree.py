"""Tests for the Git Worktree Manager."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hermetic.data.worktree import EditApplicationError, WorktreeError, WorktreeManager
from hermetic.schemas.deliverable import StructuredFileEdit


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal local git repo in tmp_path with one committed file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "hello.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


class TestWorktreeCreation:
    def test_context_manager_creates_and_removes_worktree(self, git_repo: Path) -> None:
        mgr = WorktreeManager(repo_root=git_repo, base_branch="main", task_id="task-1")
        assert not mgr.worktree_path.exists()

        with mgr as active:
            assert active.worktree_path.exists()
            assert active.worktree_path.is_dir()

        assert not mgr.worktree_path.exists()

    def test_worktree_path_is_inside_harness_directory(self, git_repo: Path) -> None:
        mgr = WorktreeManager(repo_root=git_repo, base_branch="main", task_id="task-1")
        expected_base = (git_repo / ".harness" / "worktrees").resolve()
        assert mgr.worktree_path.is_relative_to(expected_base)

    def test_worktree_contains_committed_files(self, git_repo: Path) -> None:
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="task-1") as mgr:
            hello_file = mgr.worktree_path / "hello.py"
            assert hello_file.exists()
            assert hello_file.read_text(encoding="utf-8") == "def hello():\n    return 'world'\n"

    def test_worktree_removed_on_exception_in_with_block(self, git_repo: Path) -> None:
        mgr = WorktreeManager(repo_root=git_repo, base_branch="main", task_id="task-err")
        with pytest.raises(RuntimeError, match="deliberate failure"):
            with mgr:
                assert mgr.worktree_path.exists()
                raise RuntimeError("deliberate failure")

        assert not mgr.worktree_path.exists()


class TestApplyEdits:
    def test_happy_path_single_edit_modifies_file(self, git_repo: Path) -> None:
        edit = StructuredFileEdit(
            file_path="hello.py",
            search_string="'world'",
            replacement_string="'universe'",
            expected_occurrences=1,
        )
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t1") as mgr:
            modified = mgr.apply_edits([edit])
            assert len(modified) == 1
            assert modified[0] == mgr.worktree_path / "hello.py"
            content = (mgr.worktree_path / "hello.py").read_text(encoding="utf-8")
            assert content == "def hello():\n    return 'universe'\n"

    def test_multiple_edits_applied_atomically(self, git_repo: Path) -> None:
        # Create a second file on the base repo first
        (git_repo / "second.py").write_text("value = 10\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add second"], cwd=git_repo, check=True, capture_output=True)

        edit1 = StructuredFileEdit(
            file_path="hello.py",
            search_string="'world'",
            replacement_string="'universe'",
            expected_occurrences=1,
        )
        edit2 = StructuredFileEdit(
            file_path="second.py",
            search_string="10",
            replacement_string="42",
            expected_occurrences=1,
        )

        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t2") as mgr:
            modified = mgr.apply_edits([edit1, edit2])
            assert len(modified) == 2
            assert (mgr.worktree_path / "hello.py").read_text(encoding="utf-8") == "def hello():\n    return 'universe'\n"
            assert (mgr.worktree_path / "second.py").read_text(encoding="utf-8") == "value = 42\n"

    def test_wrong_occurrence_count_raises_edit_application_error(self, git_repo: Path) -> None:
        edit = StructuredFileEdit(
            file_path="hello.py",
            search_string="'world'",
            replacement_string="'universe'",
            expected_occurrences=3,  # Actually only 1
        )
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t3") as mgr:
            with pytest.raises(EditApplicationError) as exc_info:
                mgr.apply_edits([edit])

            assert exc_info.value.expected == 3
            assert exc_info.value.actual == 1
            assert exc_info.value.file_path == "hello.py"
            assert exc_info.value.task_id == "t3"

    def test_zero_actual_occurrences_raises_edit_application_error(self, git_repo: Path) -> None:
        edit = StructuredFileEdit(
            file_path="hello.py",
            search_string="nonexistent_string",
            replacement_string="'universe'",
            expected_occurrences=1,
        )
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t4") as mgr:
            with pytest.raises(EditApplicationError) as exc_info:
                mgr.apply_edits([edit])

            assert exc_info.value.expected == 1
            assert exc_info.value.actual == 0
            assert exc_info.value.file_path == "hello.py"

    def test_file_not_found_raises_worktree_error(self, git_repo: Path) -> None:
        edit = StructuredFileEdit(
            file_path="does_not_exist.py",
            search_string="foo",
            replacement_string="bar",
            expected_occurrences=1,
        )
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t5") as mgr:
            with pytest.raises(WorktreeError, match="File not found: does_not_exist.py"):
                mgr.apply_edits([edit])

    def test_all_or_nothing_no_files_written_on_partial_failure(self, git_repo: Path) -> None:
        # Edit 1 is valid, but Edit 2 has invalid occurrence count
        edit1 = StructuredFileEdit(
            file_path="hello.py",
            search_string="'world'",
            replacement_string="'universe'",
            expected_occurrences=1,
        )
        edit2 = StructuredFileEdit(
            file_path="hello.py",
            search_string="missing_content",
            replacement_string="fail",
            expected_occurrences=1,
        )
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t6") as mgr:
            with pytest.raises(EditApplicationError):
                mgr.apply_edits([edit1, edit2])

            # hello.py must be unchanged on disk
            content = (mgr.worktree_path / "hello.py").read_text(encoding="utf-8")
            assert content == "def hello():\n    return 'world'\n"

    def test_multiline_search_string(self, git_repo: Path) -> None:
        edit = StructuredFileEdit(
            file_path="hello.py",
            search_string="def hello():\n    return 'world'\n",
            replacement_string="def greet():\n    return 'earth'\n",
            expected_occurrences=1,
        )
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t7") as mgr:
            mgr.apply_edits([edit])
            content = (mgr.worktree_path / "hello.py").read_text(encoding="utf-8")
            assert content == "def greet():\n    return 'earth'\n"

    def test_two_occurrences_with_expected_two_succeeds(self, git_repo: Path) -> None:
        (git_repo / "two.py").write_text("var = 1\nother = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add two"], cwd=git_repo, check=True, capture_output=True)

        edit = StructuredFileEdit(
            file_path="two.py",
            search_string="1",
            replacement_string="2",
            expected_occurrences=2,
        )
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t8") as mgr:
            mgr.apply_edits([edit])
            content = (mgr.worktree_path / "two.py").read_text(encoding="utf-8")
            assert content == "var = 2\nother = 2\n"


class TestCommitAndMerge:
    def test_commit_returns_sha(self, git_repo: Path) -> None:
        edit = StructuredFileEdit(
            file_path="hello.py",
            search_string="'world'",
            replacement_string="'sha-test'",
            expected_occurrences=1,
        )
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t-sha") as mgr:
            mgr.apply_edits([edit])
            sha = mgr.commit("update greeting")
            assert isinstance(sha, str)
            assert len(sha) == 40
            assert all(c in "0123456789abcdef" for c in sha)

    def test_commit_with_no_changes_raises_worktree_error(self, git_repo: Path) -> None:
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t-nochange") as mgr:
            with pytest.raises(WorktreeError, match="Nothing to commit"):
                mgr.commit()

    def test_merge_into_base_applies_changes_to_base_branch(self, git_repo: Path) -> None:
        edit = StructuredFileEdit(
            file_path="hello.py",
            search_string="'world'",
            replacement_string="'merged'",
            expected_occurrences=1,
        )
        with WorktreeManager(repo_root=git_repo, base_branch="main", task_id="t-merge") as mgr:
            mgr.apply_edits([edit])
            mgr.commit("commit in worktree")
            mgr.merge_into_base()

        # The base branch in repo_root should now have the squashed change
        content = (git_repo / "hello.py").read_text(encoding="utf-8")
        assert content == "def hello():\n    return 'merged'\n"

        # Verify commit message on base branch
        log_res = subprocess.run(
            ["git", "log", "-1", "--pretty=%B"],
            cwd=git_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "hermetic: task t-merge" in log_res.stdout
