# ADR 0001: Ephemeral Git Worktree Isolation & Deterministic Merges

## Context
To eliminate concurrency hazards during parallel task execution, we need a way to execute multiple code generation and validation steps simultaneously without them colliding in the same working directory.

## Decision
* **No Direct Working Tree Mutation**: Parallel tasks never touch the primary working branch directly.
* **Ephemeral Worktrees**: For each task in a batch, the Data Plane Git Manager creates a temporary worktree: `git worktree add -b harness/task-Ti .harness/worktrees/task-Ti <batch_base_commit>`
* **Read-Only Model Boundary**: The LLM runs with a read-only view of the code and emits structured file edits.
* **Deterministic Execution & Commits (Rebase Strategy)**:
  1. File modifications, formatters (e.g. `ruff format`), and validation commands run strictly inside the ephemeral worktree.
  2. On success, a commit is created in the worktree.
  3. The harness checks out the task branch and rebases it onto the batch branch (`harness/issue-<id>`). Because tasks within a batch are planned to touch disjoint files, the rebase applies cleanly.
  4. The temporary worktree is pruned.
