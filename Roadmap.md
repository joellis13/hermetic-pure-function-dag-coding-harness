# Project Roadmap

This document outlines planned features and architectural enhancements for the **Hermetic Pure-Function DAG AI Coding Harness** that fall outside the scope of the Phase 1 initial implementation.

## 1. Autonomous Context Assembly (Solving the Zero-Shot Discovery Problem)

**The Problem:**
Currently, the `IssueContext` is preloaded deterministically based on issue descriptions and user-supplied file paths. If a user provides a vague issue (e.g., "Fix the auth bug"), the Planning Node will not have the necessary source files in its context to formulate an accurate plan. Because AI nodes run hermetically without shell access, they cannot run `grep` or explore the codebase mid-plan.

**The Planned Solution:**
Introduce a **Research Micro-DAG** that executes *before* the Implementation Planning Micro-DAG.

1. **Research Node**: An LLM is given the raw issue description and the schema for `ContextRequest`.
2. **`ContextRequest` Schema**: Allows the LLM to request specific codebase lookups:
   - `search_regex`: e.g., `"def login"` or `"class User"`
   - `read_files`: e.g., `["src/auth.py", "tests/test_auth.py"]`
   - `find_symbols`: e.g., `"AuthService"`
3. **Deterministic Retrieval**: The Data Plane executes these queries against the local repository and populates an immutable `ResearchDossier` or expands the `IssueContext`.
4. **Iterative Loop**: The Research DAG can loop up to N times until the LLM declares it has enough context to begin planning.
5. **Handoff**: The final, populated `IssueContext` is passed to the standard Planning Micro-DAG.

This keeps the system hermetic and bounded while giving the LLM the ability to "explore" the codebase safely and deterministically.

## 2. Advanced File Editing Capabilities (Fuzzy/AST Replacement)

**The Problem:**
In the Phase 1 MVP, `SearchReplaceBlock` relies on strict, exact-character string matching. While the 3-attempt retry loop and clear prompt instructions resolve most hallucinated whitespace cases, relying on retries costs additional LLM tokens and execution time. The two lightweight Phase 1 mitigations (unique-match enforcement at prompt time, occurrence-count validation in the applier) handle the most common ambiguity failures but do not address whitespace drift or large file contexts.

**The Planned Solution:**
As the harness matures and targets larger codebases, introduce more resilient application mechanisms that preserve the deterministic boundary:
1. **Whitespace-Agnostic Matching**: The applier normalizes both the target file and the `search_target` (stripping leading/trailing lines, normalizing indent levels) to find the insertion point without demanding character-perfect whitespace from the LLM.
2. **AST-based Symbol Replacement**: Allowing the LLM to emit a `replace_symbol: "function_name"` command. The deterministic harness parses the Python AST, finds the symbol boundaries, and replaces the block. This completely bypasses the need for the LLM to echo existing code.

## 3. Per-Token Cost Tracking & Reporting

**The Problem:**
The initial implementation uses subscription-based plans (Antigravity Pro) where there is no per-token dollar cost. `NodeExecutionMetadata` tracks token counts for rate-limit awareness but does not compute dollar costs.

**The Planned Solution:**
When `DirectDriver` (LiteLLM / native APIs) is introduced in Phase 2:
1. Add `cost_usd: float | None` to `NodeExecutionMetadata`.
2. Maintain a model pricing table (input/output $/token) updatable via config.
3. Surface per-node and per-run cost estimates in `FullImplementationReport` and `full_report.html`.
4. Add a run budget cap (`--max-cost-usd`) that halts the run if projected cost exceeds the threshold.

## 4. Batch Resumption After Failure

**The Problem:**
In Phase 1, a batch failure causes a hard stop. The user must manually amend the branch or start a new run. There is no mechanism to resume from the exact point of failure.

**The Planned Solution:**
1. **Resumable Run State**: Persist per-task success/failure state in SQLite such that a `hermetic resume <run-id>` command can skip already-succeeded tasks and retry only the failed ones.
2. **Plan Amendment Flow**: Allow the user to edit individual `TaskItem` entries in `plan.json` and resume execution from a specific batch index (`hermetic resume <run-id> --from-batch 2`).
3. **Partial Batch Retry**: On resumption, re-execute only the failed tasks in a batch, not the entire batch.

## 5. DirectDriver (LiteLLM / Native SDK)

**The Problem:**
The POC exclusively uses `AntigravityDriver`. Users without an Antigravity subscription, or who need direct model API access for cost control or model selection flexibility, have no alternative.

**The Planned Solution:**
Implement `DirectDriver` as the second driver in Phase 2:
1. Uses LiteLLM for provider-agnostic API calls (Gemini, Claude, GPT-4, etc.).
2. Supports schema-constrained JSON mode (`response_format={"type": "json_object"}`).
3. Enables per-token cost tracking (see Roadmap §3).
4. Selectable via `--driver direct` CLI flag or `pyproject.toml` config.

## 6. Jira & Confluence Integration

**The Problem:**
Phase 1 supports only GitHub issues as the issue source.

**The Planned Solution:**
Add `JiraClient` and `ConfluenceAdapter` in the Data Plane `client/` and `adapter/` layers. The compute nodes depend only on `IssueContext` and `ExternalDoc` — adding these providers requires zero changes to the Planning or Execution DAGs.

## 7. Multi-Repo Task Execution

**The Problem:**
Phase 1 targets a single repository per run.

**The Planned Solution:**
The schema already supports `repo_name` / `repo_path` overrides per `TaskItem`. In a future phase, implement multi-repo batch execution where different tasks in the same plan target different local repositories.

## 8. CopilotDriver

**The Problem:**
GitHub Copilot is a widely available LLM runtime that some users may prefer.

**The Planned Solution:**
Implement `CopilotDriver` as a headless CLI / Language Server invocation. Copilot's more constrained I/O interface makes this lower priority than `DirectDriver`.
