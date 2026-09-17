"""
Git Worktree Manager — ephemeral worktree checkouts and edit application.

Provides isolated environments for task execution, all-or-nothing edit application
for StructuredFileEdits, and squash-merging back to the base branch.
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermetic.schemas.deliverable import StructuredFileEdit


@dataclass
class WorktreeError(Exception):
    """Raised for any git or edit-application failure."""

    message: str
    task_id: str | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


@dataclass
class EditApplicationError(WorktreeError):
    """Raised when occurrence-count validation fails before write."""

    file_path: str = ""
    expected: int = 0
    actual: int = 0


class WorktreeManager:
    """
    Manages an ephemeral git worktree sandbox for executing tasks in isolation.

    Validates and applies StructuredFileEdit lists atomically (all-or-nothing),
    commits the changes, and squash-merges back into the base branch.
    """

    def __init__(
        self,
        repo_root: Path,
        base_branch: str,
        task_id: str,
        worktree_base: Path | None = None,
    ) -> None:
        """
        Initialize the WorktreeManager.

        Args:
            repo_root: Root path of the git repository.
            base_branch: Branch to fork from and merge back into.
            task_id: Task identifier used for worktree path and commit messages.
            worktree_base: Base directory for worktrees, defaults to repo_root / ".harness" / "worktrees".
        """
        self._repo_root = repo_root.resolve()
        self._base_branch = base_branch
        self._task_id = task_id
        self._session_id = str(uuid.uuid4())

        base = worktree_base.resolve() if worktree_base else (self._repo_root / ".harness" / "worktrees")
        self._worktree_path = (base / self._session_id / task_id).resolve()
        self._branch_name = f"hermetic/{self._session_id}/{self._task_id}"

    @property
    def worktree_path(self) -> Path:
        """Absolute path to the checked-out worktree directory."""
        return self._worktree_path

    def __enter__(self) -> WorktreeManager:
        """Create the worktree on a new branch and return self."""
        self._worktree_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_git(
            "worktree",
            "add",
            "-b",
            self._branch_name,
            str(self._worktree_path),
            self._base_branch,
            cwd=self._repo_root,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Remove the ephemeral worktree, suppressing cleanup errors."""
        try:
            self._run_git("worktree", "remove", "--force", str(self._worktree_path), cwd=self._repo_root)
        except Exception:
            pass

        if self._worktree_path.exists():
            shutil.rmtree(self._worktree_path, ignore_errors=True)

        try:
            self._worktree_path.parent.rmdir()
        except Exception:
            pass

    def apply_edits(self, edits: list[StructuredFileEdit]) -> list[Path]:
        """
        Apply a list of StructuredFileEdits to files inside the worktree.

        Validates ALL edits before writing ANY files (all-or-nothing).
        Returns list of absolute paths that were modified.

        Raises:
            WorktreeError: If a file_path does not exist in the worktree.
            EditApplicationError: If occurrence count does not match expected_occurrences.
        """
        pending_contents: dict[Path, str] = {}

        # Pass 1: Validate all edits
        for edit in edits:
            abs_path = (self._worktree_path / edit.file_path).resolve()
            if not abs_path.exists():
                raise WorktreeError(
                    message=f"File not found: {edit.file_path}",
                    task_id=self._task_id,
                )

            if abs_path not in pending_contents:
                pending_contents[abs_path] = abs_path.read_text(encoding="utf-8")

            current_text = pending_contents[abs_path]
            actual = current_text.count(edit.search_string)
            if actual != edit.expected_occurrences:
                raise EditApplicationError(
                    message=(
                        f"Expected {edit.expected_occurrences} occurrence(s) of search string "
                        f"in {edit.file_path}, found {actual}"
                    ),
                    task_id=self._task_id,
                    file_path=edit.file_path,
                    expected=edit.expected_occurrences,
                    actual=actual,
                )

            pending_contents[abs_path] = current_text.replace(
                edit.search_string, edit.replacement_string
            )

        # Pass 2: Write all modified files
        modified_paths: list[Path] = []
        for abs_path, new_text in pending_contents.items():
            abs_path.write_text(new_text, encoding="utf-8")
            modified_paths.append(abs_path)

        return modified_paths

    def commit(self, message: str = "") -> str:
        """
        Stage all modified tracked files and commit inside the worktree.

        Returns:
            The new commit SHA.

        Raises:
            WorktreeError: If there is nothing to commit or if git fails.
        """
        self._run_git("add", "-A", cwd=self._worktree_path)

        diff_res = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=self._worktree_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if diff_res.returncode == 0:
            raise WorktreeError(message="Nothing to commit", task_id=self._task_id)
        elif diff_res.returncode != 1:
            raise WorktreeError(
                message=f"git diff --cached --quiet failed:\n{diff_res.stderr}",
                task_id=self._task_id,
            )

        commit_msg = message if message else f"hermetic: task {self._task_id}"
        self._run_git(
            "-c",
            "user.email=hermetic@local",
            "-c",
            "user.name=Hermetic",
            "commit",
            "-m",
            commit_msg,
            cwd=self._worktree_path,
        )

        res = self._run_git("rev-parse", "HEAD", cwd=self._worktree_path)
        return res.stdout.strip()

    def merge_into_base(self) -> None:
        """
        Squash-merge the worktree branch into base_branch.

        Raises:
            WorktreeError: On merge conflict or other git failure.
        """
        self._run_git("checkout", self._base_branch, cwd=self._repo_root)
        try:
            self._run_git("merge", "--squash", self._branch_name, cwd=self._repo_root)
        except WorktreeError:
            try:
                self._run_git("reset", "--merge", cwd=self._repo_root)
            except Exception:
                pass
            raise

        self._run_git(
            "-c",
            "user.email=hermetic@local",
            "-c",
            "user.name=Hermetic",
            "commit",
            "-m",
            f"hermetic: task {self._task_id}",
            cwd=self._repo_root,
        )

    def _run_git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        """
        Internal helper: run a git command, raising WorktreeError on non-zero exit code.
        """
        target_cwd = cwd if cwd is not None else self._repo_root
        result = subprocess.run(
            ["git", *args],
            cwd=target_cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise WorktreeError(
                message=f"git {' '.join(args)} failed:\n{result.stderr}",
                task_id=self._task_id,
            )
        return result
