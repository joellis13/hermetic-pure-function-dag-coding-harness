"""
Minimal DAG Engine for executing TaskBatch task graphs.

Constraints (from ImplementationPlan.md):
- Under 150 lines
- Uses graphlib.TopologicalSorter (stdlib, Python 3.9+)
- Uses asyncio.TaskGroup (stdlib, Python 3.11+)
- No external DAG frameworks

Public API:
    engine = DAGEngine(node_fn=my_async_function)
    results = await engine.execute_batch(batch)
"""
from __future__ import annotations

import asyncio
from graphlib import CycleError, TopologicalSorter
from typing import Callable, Awaitable, Generic, TypeVar

from hermetic.schemas.plan import TaskBatch, TaskItem


T = TypeVar("T")

NodeFn = Callable[[TaskItem], Awaitable[T]]


class DAGValidationError(Exception):
    """Raised when the task dependency graph is invalid (cycle, missing dep)."""


class DAGEngine(Generic[T]):
    """
    Executes a TaskBatch respecting intra-batch task dependencies.

    Generic over T — the return type of the node function. In production,
    T is TaskResult (from executor.py); in tests it may be TaskDeliverable
    or any other async-callable return type.

    Batches are the unit of execution; sequential batch ordering is
    the caller's responsibility (see the State Machine in Story 5).
    """

    def __init__(self, node_fn: NodeFn[T]) -> None:
        """
        Args:
            node_fn: An async callable that accepts a TaskItem and returns T.
                     This will be the AntigravityDriver-backed _node_fn in
                     production and a mock in tests.
        """
        self._node_fn = node_fn

    async def execute_batch(self, batch: TaskBatch) -> list[T]:
        """
        Execute all tasks in `batch`, respecting their dependency graph.

        Returns a list of T results in topological order.
        Raises DAGValidationError on cycle or missing dependency.
        Raises any exception from node_fn on task failure (no swallowing).
        """
        tasks_by_id = self._validate(batch.tasks)

        sorter: TopologicalSorter[str] = TopologicalSorter()
        for task in batch.tasks:
            sorter.add(task.id, *task.dependencies)
        sorter.prepare()

        completed: dict[str, T] = {}
        results_in_order: list[T] = []

        while sorter.is_active():
            ready_ids = list(sorter.get_ready())
            if not ready_ids:
                # No tasks ready but sorter is still active = unsatisfied deps
                break

            wave_results = await self._run_wave(
                [tasks_by_id[tid] for tid in ready_ids]
            )

            for tid, result in zip(ready_ids, wave_results):
                completed[tid] = result
                results_in_order.append(result)
                sorter.done(tid)

        if len(completed) != len(tasks_by_id):
            missing = set(tasks_by_id.keys()) - set(completed.keys())
            raise DAGValidationError(
                f"Tasks {missing} could not be executed due to unresolved dependencies."
            )

        return results_in_order

    async def _run_wave(self, tasks: list[TaskItem]) -> list[T]:
        """Run a set of ready tasks concurrently via asyncio.TaskGroup."""
        results: list[T] = [None] * len(tasks)  # type: ignore[list-item]

        async with asyncio.TaskGroup() as tg:
            for i, task in enumerate(tasks):
                async def _run(idx: int = i, t: TaskItem = task) -> None:
                    results[idx] = await self._node_fn(t)
                tg.create_task(_run())

        return results

    def _validate(self, tasks: list[TaskItem]) -> dict[str, TaskItem]:
        """Validate tasks and return a mapping of task ID to TaskItem."""
        tasks_by_id: dict[str, TaskItem] = {}
        for task in tasks:
            if task.id in tasks_by_id:
                raise DAGValidationError(f"Duplicate task id '{task.id}' found in batch.")
            tasks_by_id[task.id] = task

        known = set(tasks_by_id.keys())
        for task in tasks:
            for dep in task.dependencies:
                if dep not in known:
                    raise DAGValidationError(
                        f"Task '{task.id}' depends on '{dep}' which is not in this batch."
                    )
        return tasks_by_id
