"""Tests for hermetic.control.dag_engine — topological DAG execution."""
import asyncio
import pytest
from graphlib import CycleError

from hermetic.control.dag_engine import DAGEngine, DAGValidationError
from hermetic.schemas.plan import TaskBatch, TaskItem
from hermetic.schemas.deliverable import TaskDeliverable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(id: str, deps: list[str] | None = None) -> TaskItem:
    return TaskItem(id=id, description=f"Task {id}", instruction="do it", dependencies=deps or [])


def _make_deliverable(task: TaskItem) -> TaskDeliverable:
    return TaskDeliverable(task_id=task.id)


async def _simple_node(task: TaskItem) -> TaskDeliverable:
    """A node_fn that succeeds instantly."""
    return _make_deliverable(task)


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------

class TestDAGEngineHappyPath:
    async def test_single_task(self):
        batch = TaskBatch(tasks=[_make_item("t1")])
        engine = DAGEngine(node_fn=_simple_node)
        results = await engine.execute_batch(batch)
        assert len(results) == 1
        assert results[0].task_id == "t1"

    async def test_parallel_independent_tasks(self):
        """Three tasks with no dependencies should all run."""
        batch = TaskBatch(tasks=[_make_item("a"), _make_item("b"), _make_item("c")])
        engine = DAGEngine(node_fn=_simple_node)
        results = await engine.execute_batch(batch)
        assert {r.task_id for r in results} == {"a", "b", "c"}

    async def test_sequential_dependency_chain(self):
        """t1 -> t2 -> t3 must execute in order."""
        execution_order: list[str] = []

        async def ordered_node(task: TaskItem) -> TaskDeliverable:
            execution_order.append(task.id)
            return _make_deliverable(task)

        tasks = [
            _make_item("t1"),
            _make_item("t2", deps=["t1"]),
            _make_item("t3", deps=["t2"]),
        ]
        batch = TaskBatch(tasks=tasks)
        engine = DAGEngine(node_fn=ordered_node)
        await engine.execute_batch(batch)
        assert execution_order == ["t1", "t2", "t3"]

    async def test_diamond_dependency(self):
        """
        a
        ├─ b (dep: a)
        └─ c (dep: a)
           └─ d (dep: b, c)
        b and c must run after a; d must run after both b and c.
        """
        execution_order: list[str] = []

        async def ordered_node(task: TaskItem) -> TaskDeliverable:
            execution_order.append(task.id)
            return _make_deliverable(task)

        tasks = [
            _make_item("a"),
            _make_item("b", deps=["a"]),
            _make_item("c", deps=["a"]),
            _make_item("d", deps=["b", "c"]),
        ]
        batch = TaskBatch(tasks=tasks)
        engine = DAGEngine(node_fn=ordered_node)
        results = await engine.execute_batch(batch)

        # a must be first, d must be last
        assert execution_order[0] == "a"
        assert execution_order[-1] == "d"
        # b and c must appear before d
        idx = {t: i for i, t in enumerate(execution_order)}
        assert idx["a"] < idx["b"]
        assert idx["a"] < idx["c"]
        assert idx["b"] < idx["d"]
        assert idx["c"] < idx["d"]

    async def test_parallel_tasks_run_concurrently(self):
        """Two independent tasks that each sleep 0.05s should complete well under 0.1s total."""
        async def slow_node(task: TaskItem) -> TaskDeliverable:
            await asyncio.sleep(0.05)
            return _make_deliverable(task)

        batch = TaskBatch(tasks=[_make_item("x"), _make_item("y")])
        engine = DAGEngine(node_fn=slow_node)

        import time
        start = time.monotonic()
        await engine.execute_batch(batch)
        elapsed = time.monotonic() - start

        # If parallel: ~0.05s. If sequential: ~0.10s. Allow generous margin.
        assert elapsed < 0.09, f"Tasks appear to have run sequentially ({elapsed:.3f}s)"

    async def test_execute_batch_returns_topological_order(self):
        """Even if batch.tasks is defined in reverse order, results are in topological order."""
        tasks = [
            _make_item("task_b", deps=["task_a"]),
            _make_item("task_a"),
        ]
        batch = TaskBatch(tasks=tasks)
        engine = DAGEngine(node_fn=_simple_node)
        results = await engine.execute_batch(batch)
        assert [r.task_id for r in results] == ["task_a", "task_b"]


# ---------------------------------------------------------------------------
# Error and validation tests
# ---------------------------------------------------------------------------

class TestDAGEngineErrors:
    async def test_duplicate_task_id_raises_validation_error(self):
        """Duplicate task IDs within a batch must be rejected."""
        tasks = [
            _make_item("dup_id"),
            _make_item("dup_id"),
        ]
        batch = TaskBatch(tasks=tasks)
        engine = DAGEngine(node_fn=_simple_node)
        with pytest.raises(DAGValidationError, match="Duplicate task id 'dup_id'"):
            await engine.execute_batch(batch)

    async def test_missing_dependency_raises_validation_error(self):
        tasks = [_make_item("b", deps=["a"])]  # "a" not in batch
        batch = TaskBatch(tasks=tasks)
        engine = DAGEngine(node_fn=_simple_node)
        with pytest.raises(DAGValidationError, match="'a'"):
            await engine.execute_batch(batch)

    async def test_cycle_raises_cycle_error(self):
        """graphlib raises CycleError on prepare() for cyclic graphs."""
        tasks = [
            _make_item("a", deps=["b"]),
            _make_item("b", deps=["a"]),
        ]
        batch = TaskBatch(tasks=tasks)
        engine = DAGEngine(node_fn=_simple_node)
        with pytest.raises(CycleError):
            await engine.execute_batch(batch)

    async def test_failing_node_propagates_exception(self):
        """If node_fn raises, the exception must propagate out of execute_batch."""
        async def failing_node(task: TaskItem) -> TaskDeliverable:
            raise RuntimeError("simulated node failure")

        batch = TaskBatch(tasks=[_make_item("t1")])
        engine = DAGEngine(node_fn=failing_node)
        with pytest.raises((RuntimeError, ExceptionGroup)):
            await engine.execute_batch(batch)

    async def test_one_failure_cancels_parallel_tasks(self):
        """
        In a batch with two parallel tasks, if one fails the other should
        be cancelled (TaskGroup semantics).
        """
        started: list[str] = []
        completed: list[str] = []

        async def flaky_node(task: TaskItem) -> TaskDeliverable:
            started.append(task.id)
            if task.id == "bad":
                raise ValueError("intentional failure")
            await asyncio.sleep(1.0)  # long-running — should be cancelled
            completed.append(task.id)
            return _make_deliverable(task)

        batch = TaskBatch(tasks=[_make_item("bad"), _make_item("slow")])
        engine = DAGEngine(node_fn=flaky_node)

        with pytest.raises((ValueError, ExceptionGroup)):
            await engine.execute_batch(batch)

        # "slow" should never have completed
        assert "slow" not in completed
