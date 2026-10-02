"""
Plan Executor — drives ImplementationNode tasks across ephemeral git worktrees.

Sequential over TaskBatches, parallel within a batch (via DAGEngine).
Implements the pure-function self-healing retry loop.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from hermetic.compute.implementation_node import ImplementationError, ImplementationNode
from hermetic.control.dag_engine import DAGEngine
from hermetic.data.worktree import EditApplicationError, WorktreeError, WorktreeManager
from hermetic.schemas.deliverable import TaskDeliverable, TaskRetryContext
from hermetic.schemas.plan import ImplementationPlan, TaskItem


class TaskExecutionError(Exception):
    """Raised when a task exhausts all retry attempts."""

    def __init__(self, task_id: str, message: str) -> None:
        super().__init__(f"Task '{task_id}' failed: {message}")
        self.task_id = task_id
        self.message = message


@dataclass(frozen=True)
class TaskResult:
    """Bundles a TaskDeliverable with its token-usage metadata from one task execution."""

    deliverable: TaskDeliverable
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ExecutionResult:
    """Aggregated result of executing an entire ImplementationPlan.

    Only returned on full success — `execute_plan` raises `TaskExecutionError` on any
    task failure (hard-stop). Failed task identity is carried by the exception, not here.
    """

    deliverables: list[TaskDeliverable]
    total_input_tokens: int
    total_output_tokens: int


def _validate_worktree(path: Path) -> str | None:
    """
    Run ruff check on the worktree path if ruff is available.
    Returns an error string on failure, None on success or if ruff is not found.
    """
    ruff = shutil.which("ruff")
    if ruff is None:
        return None

    result = subprocess.run(
        [ruff, "check", "."],
        cwd=path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return result.stdout + result.stderr
    return None


async def _execute_task_with_retry(
    task: TaskItem,
    impl_node: ImplementationNode,
    repo_root: Path,
    base_branch: str,
    max_retries: int,
    worktree_base: Path | None,
) -> TaskResult:
    """
    Execute a single TaskItem with retry loop.

    Returns a TaskResult on success.
    Raises TaskExecutionError after all retries are exhausted.
    """
    attempt = 0
    previous_deliverable: TaskDeliverable | None = None
    last_error = ""
    total_input = 0
    total_output = 0

    while attempt <= max_retries:
        retry_ctx: TaskRetryContext | None = None
        if attempt > 0:
            retry_ctx = TaskRetryContext(
                task_id=task.id,
                error_message=last_error,
                retry_count=attempt - 1,
                previous_deliverable=previous_deliverable,
            )

        try:
            deliverable, meta = await impl_node.implement(task, retry_ctx)
            total_input += meta.input_tokens
            total_output += meta.output_tokens
        except ImplementationError as e:
            last_error = str(e)
            attempt += 1
            continue

        # Apply edits in an ephemeral worktree
        with WorktreeManager(repo_root, base_branch, task.id, worktree_base) as wt:
            try:
                wt.apply_edits(deliverable.edits)
                lint_error = _validate_worktree(wt.worktree_path)
                if lint_error:
                    raise WorktreeError(message=lint_error, task_id=task.id)
                wt.commit(f"hermetic: {task.id} (attempt {attempt})")
                wt.merge_into_base()
                return TaskResult(  # ✅ success
                    deliverable=deliverable,
                    input_tokens=total_input,
                    output_tokens=total_output,
                )
            except (WorktreeError, EditApplicationError) as e:
                last_error = str(e)
                previous_deliverable = deliverable
                attempt += 1

    raise TaskExecutionError(task_id=task.id, message=last_error)


async def execute_plan(
    plan: ImplementationPlan,
    repo_root: Path,
    base_branch: str,
    impl_node: ImplementationNode,
    *,
    max_retries: int = 3,
    worktree_base: Path | None = None,
) -> ExecutionResult:
    """
    Execute all batches in an ImplementationPlan sequentially.

    Within each batch, tasks run in parallel (respecting intra-batch dependencies)
    via DAGEngine. If any task exhausts all retries, TaskExecutionError is raised
    immediately (hard stop — no partial batch success).

    Args:
        plan: The approved ImplementationPlan to execute.
        repo_root: Root of the git repository to operate on.
        base_branch: Branch to fork worktrees from and merge back into.
        impl_node: The ImplementationNode to invoke per task.
        max_retries: Maximum retry attempts per task (0 = one attempt only).
        worktree_base: Override base directory for ephemeral worktrees.

    Returns:
        ExecutionResult with all successful deliverables and aggregated token counts.

    Raises:
        TaskExecutionError: If a task exhausts all retries (hard stop).
    """
    all_deliverables: list[TaskDeliverable] = []
    total_input = 0
    total_output = 0

    # Define _node_fn once, outside the batch loop.  impl_node, repo_root, etc. are
    # outer function parameters and do not vary between batches, so no late-binding
    # hazard exists and the default-argument capture trick is unnecessary.
    async def _node_fn(task: TaskItem) -> TaskResult:
        # Returns an immutable TaskResult — no shared mutable state.
        return await _execute_task_with_retry(
            task, impl_node, repo_root, base_branch, max_retries, worktree_base
        )

    for batch in plan.batches:
        engine: DAGEngine[TaskResult] = DAGEngine(_node_fn)
        try:
            batch_results: list[TaskResult] = await engine.execute_batch(batch)
        except TaskExecutionError:
            raise
        except BaseExceptionGroup as eg:
            match, _ = eg.split(TaskExecutionError)
            if match is not None:
                def _find_err(e: BaseException) -> TaskExecutionError | None:
                    if isinstance(e, TaskExecutionError):
                        return e
                    if isinstance(e, BaseExceptionGroup):
                        for sub in e.exceptions:
                            found = _find_err(sub)
                            if found:
                                return found
                    return None

                err = _find_err(match)
                if err:
                    raise err
            raise

        for result in batch_results:
            all_deliverables.append(result.deliverable)
            total_input += result.input_tokens
            total_output += result.output_tokens

    return ExecutionResult(
        deliverables=all_deliverables,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )
