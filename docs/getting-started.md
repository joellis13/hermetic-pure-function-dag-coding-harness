# Getting Started

This guide walks you through installing the harness, running the test suite, and executing your first planning run against a GitHub issue.

---

## 1. Prerequisites

### Required

| Tool | Version | Install |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.4 | `pip install uv` or `winget install astral-sh.uv` |
| Git | any recent | [git-scm.com](https://git-scm.com/) |
| Google Antigravity | subscription | For live AI calls (not needed to run tests) |

### Python

Do **not** install Python 3.13 manually. `uv` downloads and manages it automatically when you run `uv sync`. The version is pinned in `.python-version`.

> **Why 3.13?** Full Pydantic v2 support, 100% precompiled binary wheel availability on Windows, improved error messages. Python 3.14 is avoided due to Rust/Pydantic binary wheel build issues.

---

## 2. Installation

```powershell
# Clone the repository
git clone https://github.com/<owner>/hermetic-pure-function-dag-coding-harness
cd hermetic-pure-function-dag-coding-harness

# Install all dependencies (creates .venv, downloads Python 3.13 if needed)
uv sync

# Confirm the CLI entry point works
uv run hermetic --help
```

You should see the Typer help output listing the available commands.

---

## 3. Running the Test Suite

The full test suite runs in ~6 seconds with zero network calls:

```powershell
uv run pytest tests/ -v
```

Expected output:
```
155 passed, 3 skipped in 6.07s
```

The 3 skipped tests are **live mode** tests that make real network calls (GitHub + Antigravity). They are intentionally skipped in normal runs. To enable them:

```powershell
$env:HERMETIC_RUN_LIVE_TESTS = "1"
uv run pytest tests/ -v -m ""
```

---

## 4. Environment Variables

Set these before running CLI commands:

```powershell
# Required for hermetic plan (GitHub issue fetch)
$env:GITHUB_TOKEN  = "ghp_..."      # GitHub PAT with repo read scope
$env:GITHUB_OWNER  = "myorg"        # Default org/user (overridable per-run with --owner)
$env:GITHUB_REPO   = "my-repo"      # Default repo name (overridable per-run with --github-repo)

# Optional: enable live model + GitHub tests
$env:HERMETIC_RUN_LIVE_TESTS = "1"
```

On Linux/macOS, use `export VAR=value` instead of `$env:VAR = "value"`.

---

## 5. Your First Planning Run

> **Story 5 prerequisite:** The `plan`, `review`, and `approve` commands are implemented in Story 5. If you are on Stories 1–4, skip this section.

### Step 1 — Generate a plan

```powershell
uv run hermetic plan 42 --repo . --owner myorg --github-repo my-repo
```

This will:
1. Fetch GitHub issue #42 via GraphQL.
2. Build an `IssueContext` from the issue title and body.
3. Call the `PlanningNode` (Claude Sonnet by default) to produce an `ImplementationPlan`.
4. Run the `CriticNode` (cross-provider — Gemini) for an adversarial review.
5. Save the plan as version 1 in `.harness/state.db`.
6. Render `.harness/runs/<run-id>/plan.html`.

Output looks like:
```
┌─ Hermetic Plan ──────────────────────────────────────────┐
│  Run ID   : a3f7c8d2-1234-...                            │
│  Issue    : GH-42 — Add retry logic to WorktreeManager   │
│  Batches  : 2                                            │
│  Tasks    : 5                                            │
│  Critic   : ✓ Approved (gemini-3-1-pro)                  │
│  Plan     : .harness/runs/a3f7c8d2-.../plan.html         │
└──────────────────────────────────────────────────────────┘

Next steps:
  hermetic review a3f7c8d2-...    (optional — refine with feedback)
  hermetic approve a3f7c8d2-...   (mark plan ready for execution)
```

### Step 2 — Review and refine (optional)

```powershell
uv run hermetic review a3f7c8d2-...
```

The command prints the current plan as a table and prompts for feedback:

```
Enter feedback (empty to exit without changes): Add integration tests to batch 2
```

On non-empty input, a revised `plan_v2` is generated and saved. You can iterate as many times as needed.

### Step 3 — Approve

```powershell
uv run hermetic approve a3f7c8d2-...
```

This marks the run status as `approved` in SQLite. No code is written yet — approval is a gate for Story 6 execution.

### Step 4 — Execute (Story 6)

```powershell
uv run hermetic implement a3f7c8d2-...
```

Executes the approved plan across ephemeral git worktrees, runs linters/tests, and merges passing batches.

---

## 6. Runtime Data (.harness/)

The `.harness/` directory is created automatically on first run and is gitignored:

```text
.harness/
├── state.db          # SQLite: runs table + plan_checkpoints table
├── worktrees/        # Ephemeral git worktrees (created and pruned per batch)
└── runs/
    └── <run-id>/
        ├── plan.html           # Rendered plan (opens in any browser)
        └── full_report.html    # Post-execution report (Story 6)
```

To inspect the database directly:

```powershell
# List all runs
uv run python -c "
import asyncio, aiosqlite
async def main():
    async with aiosqlite.connect('.harness/state.db') as db:
        async with db.execute('SELECT run_id, issue_id, status, created_at FROM runs') as cur:
            async for row in cur: print(row)
asyncio.run(main())
"
```

---

## 7. Troubleshooting

### `uv run hermetic` — ModuleNotFoundError

Run `uv sync` first. The `.venv` must be populated before the entry point works.

### `GitHubClientError: 401 Unauthorized`

Your `GITHUB_TOKEN` is missing or expired. Generate a new PAT at [github.com/settings/tokens](https://github.com/settings/tokens) with `repo` (read) scope.

### `PlanningError: AI response cannot be parsed`

The `AntigravityDriver` returned a response that couldn't be sanitized into valid `ImplementationPlan` JSON. This is rare with Claude Sonnet. Try re-running — if it persists, file an issue with the `--debug` flag output (Story 6 adds `--debug`).

### Tests fail with `ImportError`

Make sure you're using `uv run pytest`, not a globally installed `pytest`. The project's dependencies live in the `uv`-managed `.venv`.
