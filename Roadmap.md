# Project Roadmap

This document outlines planned features and architectural enhancements for the **Hermetic Pure-Function DAG AI Coding Harness** that fall outside the scope of the Phase 1 initial implementation. These are structured as high-level stories for future implementation phases.

### Story 7: Autonomous Context Assembly (Solving the Zero-Shot Discovery Problem)
*Goal: Solve the zero-shot discovery problem by letting the AI safely explore the codebase before planning.*
**The Problem:**
Currently, the `IssueContext` is preloaded deterministically based on issue descriptions and user-supplied file paths. If a user provides a vague issue (e.g., "Fix the auth bug"), the Planning Node will not have the necessary source files in its context to formulate an accurate plan. Because AI nodes run hermetically without shell access, they cannot run `grep` or explore the codebase mid-plan.

**The Planned Solution:**
Introduce a **Research Micro-DAG** that executes *before* the Implementation Planning Micro-DAG.
- **Research Node**: An LLM is given the raw issue description and the schema for `ContextRequest`.
- **`ContextRequest` Schema**: Allows the LLM to request specific codebase lookups:
  - `search_regex`: e.g., `"def login"` or `"class User"`
  - `read_files`: e.g., `["src/auth.py", "tests/test_auth.py"]`
  - `find_symbols`: e.g., `"AuthService"`
- **Deterministic Retrieval**: The Data Plane executes these queries against the local repository and populates an immutable `ResearchDossier` or expands the `IssueContext`.
- **Iterative Loop**: The Research DAG can loop up to N times until the LLM declares it has enough context to begin planning.
- **Handoff**: The final, populated `IssueContext` is passed to the standard Planning Micro-DAG.

This keeps the system hermetic and bounded while giving the LLM the ability to "explore" the codebase safely and deterministically.

### Story 8: Advanced File Editing Capabilities (Fuzzy/AST Replacement)
*Goal: Increase resilience of file modifications beyond exact-character string matching.*
**The Problem:**
In the Phase 1 MVP, `SearchReplaceBlock` relies on strict, exact-character string matching. While the 3-attempt retry loop and clear prompt instructions resolve most hallucinated whitespace cases, relying on retries costs additional LLM tokens and execution time. The two lightweight Phase 1 mitigations handle the most common ambiguity failures but do not address whitespace drift or large file contexts.

**The Planned Solution:**
As the harness matures and targets larger codebases, introduce more resilient application mechanisms that preserve the deterministic boundary:
- **Whitespace-Agnostic Matching**: The applier normalizes both the target file and the `search_target` (stripping leading/trailing lines, normalizing indent levels) to find the insertion point without demanding character-perfect whitespace from the LLM.
- **AST-based Symbol Replacement**: Allowing the LLM to emit a `replace_symbol: "function_name"` command. The deterministic harness parses the Python AST, finds the symbol boundaries, and replaces the block. This completely bypasses the need for the LLM to echo existing code.

### Story 9: Per-Token Cost Tracking & Reporting
*Goal: Provide dollar-cost estimation and budget caps for direct API usage.*
**The Problem:**
The initial implementation uses subscription-based plans (Antigravity Pro) where there is no per-token dollar cost. `NodeExecutionMetadata` tracks token counts for rate-limit awareness but does not compute dollar costs.

**The Planned Solution:**
When `DirectDriver` (LiteLLM / native APIs) is introduced in Phase 2:
- Add `cost_usd: float | None` to `NodeExecutionMetadata`.
- Maintain a model pricing table (input/output $/token) updatable via config.
- Surface per-node and per-run cost estimates in `FullImplementationReport` and `full_report.html`.
- Add a run budget cap (`--max-cost-usd`) that halts the run if projected cost exceeds the threshold.

### Story 10: Batch Resumption After Failure
*Goal: Allow the harness to recover from a hard stop without restarting from scratch.*
**The Problem:**
In Phase 1, a batch failure causes a hard stop. The user must manually amend the branch or start a new run. There is no mechanism to resume from the exact point of failure.

**The Planned Solution:**
- **Resumable Run State**: Persist per-task success/failure state in SQLite such that a `hermetic resume <run-id>` command can skip already-succeeded tasks and retry only the failed ones.
- **Plan Amendment Flow**: Allow the user to edit individual `TaskItem` entries in `plan.json` and resume execution from a specific batch index (`hermetic resume <run-id> --from-batch 2`).
- **Partial Batch Retry**: On resumption, re-execute only the failed tasks in a batch, not the entire batch.

### Story 11: DirectDriver (LiteLLM / Native SDK)
*Goal: Support users without Antigravity subscriptions or those needing direct API access.*
**The Problem:**
The POC exclusively uses `AntigravityDriver`. Users without an Antigravity subscription, or who need direct model API access for cost control or model selection flexibility, have no alternative.

**The Planned Solution:**
Implement `DirectDriver` as the second driver in Phase 2:
- Uses LiteLLM for provider-agnostic API calls (Gemini, Claude, GPT-4, etc.).
- Supports schema-constrained JSON mode (`response_format={"type": "json_object"}`).
- Enables per-token cost tracking (see Roadmap §3).
- Selectable via `--driver direct` CLI flag or `pyproject.toml` config.

### Story 12: Jira & Confluence Integration
*Goal: Expand external client support beyond GitHub issues.*
**The Problem:**
Phase 1 supports only GitHub issues as the issue source.

**The Planned Solution:**
Add `JiraClient` and `ConfluenceAdapter` in the Data Plane `client/` and `adapter/` layers. The compute nodes depend only on `IssueContext` and `ExternalDoc` — adding these providers requires zero changes to the Planning or Execution DAGs.

### Story 13: Multi-Repo Task Execution
*Goal: Support orchestrated changes across multiple repositories in a single run.*
**The Problem:**
Phase 1 targets a single repository per run.

**The Planned Solution:**
The schema already supports `repo_name` / `repo_path` overrides per `TaskItem`. In a future phase, implement multi-repo batch execution where different tasks in the same plan target different local repositories.

### Story 14: CopilotDriver
*Goal: Support GitHub Copilot as an alternative headless AI runtime.*
**The Problem:**
GitHub Copilot is a widely available LLM runtime that some users may prefer.

**The Planned Solution:**
Implement `CopilotDriver` as a headless CLI / Language Server invocation. Copilot's more constrained I/O interface makes this lower priority than `DirectDriver`.
