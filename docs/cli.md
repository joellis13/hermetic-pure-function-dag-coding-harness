# CLI Reference

The `hermetic` CLI is implemented with [Typer](https://typer.tiangolo.com/) and [Rich](https://rich.readthedocs.io/).

All commands are invoked via `uv run hermetic <command> [OPTIONS]`.

> **Story 5 note:** `plan`, `review`, and `approve` are implemented in Story 5.  
> **Story 6 note:** `implement` is implemented in Story 6.

---

## Global Options

| Option | Description |
|---|---|
| `--help` | Show help and exit. |
| `--version` | Show the installed version. |

---

## `hermetic plan`

Fetch a GitHub issue, generate an `ImplementationPlan` via the Planning Node, run a cross-provider Critic review, and save the result as a versioned checkpoint.

```
hermetic plan ISSUE_NUMBER [OPTIONS]
```

### Arguments

| Argument | Description |
|---|---|
| `ISSUE_NUMBER` | GitHub issue number (integer). |

### Options

| Option | Default | Env Var | Description |
|---|---|---|---|
| `--repo PATH` | `.` | — | Path to the target git repository root. |
| `--branch TEXT` | `main` | — | Base branch to plan against. |
| `--model TEXT` | `claude-sonnet-4-6` | — | Planner model string. |
| `--owner TEXT` | — | `GITHUB_OWNER` | GitHub org or user name. |
| `--github-repo TEXT` | — | `GITHUB_REPO` | GitHub repository name. |
| `--token TEXT` | — | `GITHUB_TOKEN` | GitHub personal access token. |
| `--db PATH` | `<repo>/.harness/state.db` | — | Path to the SQLite state database. |
| `--output PATH` | `<repo>/.harness/runs/<run-id>/` | — | Directory to write `plan.html`. |
| `--no-critic` | (critic enabled) | — | Skip the CriticNode evaluation step. |

### Behavior

1. Validates `--repo` is a git repository.
2. Fetches the GitHub issue via GraphQL (`title`, `body`, `url`).
3. Builds an `IssueContext` from the issue.
4. Creates a new run entry in SQLite (status: `planning`).
5. Calls the `PlanningNode` → `ImplementationPlan`.
6. Unless `--no-critic`: runs `CriticNode` (cross-provider). Critic verdict is printed but **does not block** saving the plan.
7. Saves the plan as version 1 checkpoint (with `context_json` stored for offline `review`).
8. Renders `plan.html` to the output directory.
9. Prints a Rich summary panel with the run ID, plan stats, critic verdict, and next steps.

### Example

```powershell
$env:GITHUB_TOKEN = "ghp_..."
uv run hermetic plan 42 --repo . --owner myorg --github-repo my-repo
```

---

## `hermetic review`

Interactively review the latest plan checkpoint for a run, submit feedback, and generate a revised plan.

```
hermetic review RUN_ID [OPTIONS]
```

### Arguments

| Argument | Description |
|---|---|
| `RUN_ID` | Run ID returned by `hermetic plan`. |

### Options

| Option | Default | Description |
|---|---|---|
| `--version INT` | latest | Review a specific checkpoint version instead of the latest. |
| `--repo PATH` | `.` | Path to the target git repository root. |
| `--db PATH` | `<repo>/.harness/state.db` | Path to the SQLite state database. |
| `--model TEXT` | `claude-sonnet-4-6` | Planner model for the revision call. |
| `--no-critic` | (critic enabled) | Skip the CriticNode after generating the revised plan. |

### Behavior

1. Loads the run and the specified/latest plan checkpoint from SQLite.
2. Prints the plan as a Rich table (batch → task descriptions).
3. Prompts: `Enter feedback (empty to exit without changes):`.
4. If feedback is empty → exits cleanly, no new checkpoint written.
5. If feedback is provided:
   - Builds a `PlanIterationContext(iteration=<current_version>, feedback=<text>)`.
   - Re-hydrates `IssueContext` from the stored `context_json` in the run (no second GitHub fetch required).
   - Calls `PlanningNode` with the iteration context → revised plan.
   - Unless `--no-critic`: runs `CriticNode`. If the critic rejects, prints the critique and asks `Proceed anyway? [y/N]`. On `N`, the revised plan is discarded.
   - Saves the revised plan as a new version checkpoint.
   - Re-renders `plan.html`.
6. Prints a summary with the new version number.

### Example

```powershell
uv run hermetic review a3f7c8d2-1234-...
# > Enter feedback: Add integration tests to batch 2
# Saved plan_v2. Run `hermetic approve a3f7c8d2-...` to approve.
```

---

## `hermetic approve`

Approve the latest (or a specific) plan checkpoint, marking the run as ready for execution.

```
hermetic approve RUN_ID [OPTIONS]
```

### Arguments

| Argument | Description |
|---|---|
| `RUN_ID` | Run ID to approve. |

### Options

| Option | Default | Description |
|---|---|---|
| `--version INT` | latest | Approve a specific version instead of the latest. |
| `--repo PATH` | `.` | Path to the target git repository root. |
| `--db PATH` | `<repo>/.harness/state.db` | Path to the SQLite state database. |

### Behavior

1. Loads the run from SQLite. Errors if status is not `planning`.
2. Loads the specified/latest plan checkpoint.
3. Prints a Rich plan summary table.
4. Prompts: `Approve this plan and mark run ready for execution? [y/N]`.
5. On `Y`: updates run status to `approved` in SQLite.
6. On `N`: exits without changes.
7. Prints next step: `hermetic implement <run-id>`.

> **Design principle:** The Critic is advisory — it never blocks approval. Only explicit user confirmation via `hermetic approve` changes the run status.

### Example

```powershell
uv run hermetic approve a3f7c8d2-1234-...
# > Approve this plan? [y/N]: y
# ✓ Run a3f7c8d2-... approved. Run `hermetic implement a3f7c8d2-...` to execute.
```

---

## `hermetic implement` _(Story 6)_

Execute an approved plan across ephemeral git worktrees, run linters/tests per task, and merge passing batches.

```
hermetic implement RUN_ID [OPTIONS]
```

> Implemented in Story 6. See [ImplementationPlan.md](../ImplementationPlan.md) for details.

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | User error (bad arguments, missing credentials, run not found) |
| `2` | AI error (PlanningError, unrecoverable sanitization failure) |
| `3` | Git error (WorktreeError during execution) |
