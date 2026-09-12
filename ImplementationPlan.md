# Implementation Plan: Hermetic Pure-Function DAG AI Coding Harness

This plan extracts the "what we need now" (Phase 0 - 1e) to achieve the POC (dogfooding). Features and architectural enhancements deferred for later are tracked in `Roadmap.md`.

---

## Part 1: What We Need Now (POC / Phase 0 - 1e)

The core requirement for the POC is to build enough of the harness so it can plan and implement an update on itself ("dogfooding"). This includes project scaffolding, core schemas, DAG execution, worktree isolation, Antigravity integration, state machine, and basic HTML rendering.

### Story 1: Project Scaffolding (Phase 0)
*Goal: Set up the Python 3.12 environment, dependencies, and directory structure.*
- **Details:** 
  - Use Python 3.12 pinned via `uv` to ensure maximum performance and 100% precompiled binary wheel availability on Windows.
  - 100% `uv` project management to eliminate global package contamination (deps locked in `uv.lock`).
- **Task 1.1:** Initialize the Python 3.12 project with `uv` and define dependencies (`pydantic>=2.0`, `typer`, `rich`, `jinja2`, `aiosqlite`, `pytest`) in `pyproject.toml`.
- **Task 1.2:** Create the project directory layout (`src/hermetic/cli`, `control`, `data`, `compute`, `schemas`, and `tests`).
- **Task 1.3:** Create the `.gitignore` to exclude `.harness/` (state, cache, worktrees, runs) and `.python-version`.

### Story 2: Core Schemas and Utilities (Phase 1a)
*Goal: Define the Pydantic contracts and pure-Python utilities that form the deterministic backbone.*
- **Details:** 
  - Schemas are strictly typed and serializable to JSON. `ImplementationPlan` includes sequential `TaskBatch`es containing parallel `TaskItem`s.
  - The JSON Sanitizer must provide a two-tier defense: stripping markdown fences/trailing commas, and capturing Pydantic validation errors for a repair loop.
  - The DAG Engine must be minimal (under 150 lines), utilizing Python's built-in `graphlib.TopologicalSorter` and `asyncio.TaskGroup`, strictly without external framework bloat (no Airflow/LangGraph).
- **Task 2.1:** Implement Context Schemas (`IssueContext`, `CodeSnippet`, `ExternalDoc`) in `src/hermetic/schemas/context.py`.
- **Task 2.2:** Implement Plan Schemas (`ImplementationPlan`, `TaskBatch`, `TaskItem`, `PlanIterationContext`) in `src/hermetic/schemas/plan.py`.
- **Task 2.3:** Implement Deliverable Schemas (`TaskDeliverable`, `StructuredFileEdit`, `TaskRetryContext`, `FullImplementationReport`) in `src/hermetic/schemas/deliverable.py`.
- **Task 2.4:** Implement Research and Review Schemas in `src/hermetic/schemas/research.py` and `review.py`.
- **Task 2.5:** Implement JSON Sanitizer (`sanitizer.py`) for deterministic parsing.
- **Task 2.6:** Implement Content-Addressable Cache (`cache.py`) using SHA256 of inputs.
- **Task 2.7:** Implement Minimal DAG Engine (`dag_engine.py`).
- **Task 2.8:** Write test suite for schemas, sanitizer, cache, and DAG engine.

### Story 3: Data Plane and File Operations (Phase 1b)
*Goal: Implement local git worktree isolation, file formatting, HTML rendering, and context assembly.*
- **Details:**
  - Tasks within a batch execute concurrently in isolated ephemeral `git worktree` sandboxes to entirely eliminate concurrency hazards.
  - `StructuredFileEdit` applies exact-string matching with occurrence-count validation before applying replacements.
  - Context Assembler enforces soft token budget caps (150k for Planning/Review, 750k for Implementation) using a character-count approximation.
- **Task 3.1:** Implement Git Worktree Manager (`worktree.py`) to create ephemeral sandboxes, apply structured edits, and run git merges.
- **Task 3.2:** Implement HTML Renderer (`renderer/` + Jinja2) for auto-rendering `plan.html` and `full_report.html` from JSON schemas.
- **Task 3.3:** Implement Context Assembler (`etl/`) to build `IssueContext` with token budget enforcement.
- **Task 3.4:** Write test suite for the Data Plane using local git fixtures.

### Story 4: AI Compute and Walking Skeleton (Phase 1c)
*Goal: Connect the deterministic harness to the Antigravity LLM backend.*
- **Details:**
  - All executions are stateless, non-interactive invocations. The `AgentDriver` abstract interface natively extracts token counts (`usage_metadata`) and latency.
  - By default, Antigravity uses Claude Sonnet for Research/Planning/Review and Gemini Flash for Implementation tasks.
  - The Critic Node uses cross-provider evaluation (or an adversarial persona fallback) to prevent the planning node from rubber-stamping its own mistakes.
- **Task 4.1:** Define `AgentDriver` ABC and implement `AntigravityDriver`.
- **Task 4.2:** Implement Critic Node (`critic.py`) using the cross-provider fallback setup.
- **Task 4.3:** Build a "Walking Skeleton" script to ingest a local JSON fixture and output a rendered `plan.html`.
- **Task 4.4:** Write integration tests for the `AgentDriver` (with mocked and live modes).

### Story 5: Planning Workflow and CLI (Phase 1d)
*Goal: Implement the interactive CLI, GitHub issue fetching, and state suspension.*
- **Details:**
  - Interactive HITL (Human-in-the-Loop) refinement relies strictly on pure functional state transitions (`Plan_{n+1} = PlanningNode(IssueContext, Plan_n, UserFeedback)`), avoiding accumulation of raw, noisy conversational transcripts.
  - User feedback generates versioned checkpoints (`plan_v1.json`, `plan_v2.json`) in SQLite, enabling instant rollback capabilities.
- **Task 5.1:** Implement GitHub Client (`client/github.py`) for GraphQL data fetching.
- **Task 5.2:** Implement State Machine (`state_machine.py`) with SQLite persistence for runs and versioned checkpoints.
- **Task 5.3:** Implement CLI commands (`plan`, `review`, `approve`) using Typer/Rich.
- **Task 5.4:** Perform a Self-Hosting planning test (generating a plan for the harness, on the harness codebase via `--repo .`).

### Story 6: Execution Workflow and Dogfooding (Phase 1e)
*Goal: Execute plans across ephemeral worktrees and merge successful batches.*
- **Details:**
  - Employs a pure-function self-healing loop: failed linters/tests generate a `TaskRetryContext` sent back to the model (up to 3 retries).
  - Hard-stop on batch failure: If any task in a batch fails all retries, the run halts immediately to preserve sequence integrity.
  - Generates a `FullImplementationReport` aggregating task deliverables, diffs, test summaries, and token counts.
- **Task 6.1:** Implement the `implement` CLI command wired to the DAG, driving parallel worktrees, retry loops, and branch merges.
- **Task 6.2:** Implement aggregation logic to generate `FullImplementationReport` and render `full_report.html`.
- **Task 6.3:** **Dogfooding Run** - Run the complete pipeline to plan and implement an actual feature/fix on the codebase itself.
