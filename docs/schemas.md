# Schema Reference

All schemas live in `src/hermetic/schemas/` and are importable from `hermetic.schemas`. They are **Pydantic v2 models** — strictly typed, JSON-serializable, and frozen (immutable after construction).

---

## Context Schemas (`context.py`)

### `IssueContext`

The complete hermetic context bundle passed to AI compute nodes. Immutable once constructed.

```python
class IssueContext(BaseModel):
    issue_id: str        # Source-system ID, e.g. "GH-42" or "JIRA-100"
    title: str           # Issue title / one-liner
    description: str     # Full issue body in Markdown
    snippets: list[CodeSnippet]   # Code fragments from the repository
    docs: list[ExternalDoc]       # External documentation pages
```

### `CodeSnippet`

A slice of source code from a file, with a validated line range.

```python
class CodeSnippet(BaseModel):
    file_path: str    # Repo-relative path, e.g. "src/hermetic/schemas/context.py"
    content: str      # Verbatim source text of the snippet
    start_line: int   # 1-indexed first line (inclusive)
    end_line: int     # 1-indexed last line (inclusive); must be >= start_line
```

### `ExternalDoc`

A piece of documentation fetched from an external URL.

```python
class ExternalDoc(BaseModel):
    url: str             # Canonical URL of the document
    content: str         # Markdown or plain-text body
    title: str | None    # Optional document title
```

---

## Plan Schemas (`plan.py`)

### `ImplementationPlan`

The top-level artifact produced by the `PlanningNode`. Batches are ordered: `batch[0]` executes first. Within each batch, tasks may run concurrently per their dependency graph.

```python
class ImplementationPlan(BaseModel):
    plan_id: str              # UUID (auto-generated)
    issue_id: str             # Must match IssueContext.issue_id
    batches: list[TaskBatch]  # At least 1 batch required
    iteration_context: PlanIterationContext
```

### `TaskBatch`

An ordered set of `TaskItem`s forming one logical phase of the plan. Tasks within a batch whose dependencies are satisfied execute in parallel.

```python
class TaskBatch(BaseModel):
    batch_id: str           # UUID (auto-generated)
    description: str        # Human-readable label for this batch
    tasks: list[TaskItem]   # At least 1 task required
```

### `TaskItem`

A single atomic coding task. The `instruction` field is the complete prompt sent to the Implementation Node.

```python
class TaskItem(BaseModel):
    id: str               # Unique task ID (UUID or human-readable slug)
    description: str      # One-line summary for display
    instruction: str      # Full self-contained prompt for the Implementation Node
    dependencies: list[str]  # IDs of TaskItems that must complete first (same batch only)
```

### `PlanIterationContext`

Carries HITL feedback from one planning iteration to the next. Used by `PlanningNode` to construct revision prompts.

```python
class PlanIterationContext(BaseModel):
    iteration: int    # 0 = initial plan, 1+ = revised plan
    feedback: str     # User or Critic feedback from the previous iteration
```

---

## Deliverable Schemas (`deliverable.py`)

### `TaskDeliverable`

All file edits produced by one `TaskItem` execution.

```python
class TaskDeliverable(BaseModel):
    task_id: str                      # ID of the TaskItem this satisfies
    edits: list[StructuredFileEdit]   # May be empty for no-op tasks
    explanation: str                  # Optional reasoning from the Implementation Node
```

### `StructuredFileEdit`

A deterministic search-and-replace file edit. The Data Plane applier validates occurrence count before writing.

```python
class StructuredFileEdit(BaseModel):
    file_path: str            # Repo-relative path of the file to edit
    search_string: str        # Exact string to locate (verbatim)
    replacement_string: str   # Exact replacement for every matched occurrence
    expected_occurrences: int # Applier rejects if this many occurrences are not found (default: 1)
```

### `TaskRetryContext`

Feedback fed back to the Implementation Node on a retry. Contains the error output so the model can self-correct.

```python
class TaskRetryContext(BaseModel):
    task_id: str
    error_message: str                        # Linter / test failure output
    retry_count: int                          # 0-indexed; hard cap at 3
    previous_deliverable: TaskDeliverable | None
```

### `FullImplementationReport`

Aggregated result of an entire plan execution run. Also the data model for `full_report.html`.

```python
class FullImplementationReport(BaseModel):
    plan_id: str
    deliverables: list[TaskDeliverable]
    failed_tasks: list[str]        # task_ids that exhausted all retries
    summary: str
    total_input_tokens: int
    total_output_tokens: int
```

---

## Review Schemas (`review.py`)

### `ReviewFeedback`

Structured verdict from the `CriticNode`. If `approved` is `False`, `comments` and `suggested_changes` are fed into the next `PlanIterationContext`.

```python
class ReviewFeedback(BaseModel):
    approved: bool                          # True = plan accepted; False = revision required
    comments: str                           # Explanation of the verdict
    suggested_changes: list[StructuredFileEdit]  # Concrete edits the Critic recommends
```

---

## Research Schemas (`research.py`)

Used by the Research Micro-DAG (Story 7 — Autonomous Context Assembly).

### `ResearchQuery`

A structured codebase lookup request emitted by the Research Node.

```python
class ResearchQuery(BaseModel):
    query: str                # Natural-language description of what to find
    purpose: str              # Why this information is needed for the plan
    search_regex: str | None  # Optional regex to run via grep/ripgrep
    read_files: list[str]     # Repo-relative file paths to read in full
```

### `ResearchResult`

The Data Plane's response to a `ResearchQuery`.

```python
class ResearchResult(BaseModel):
    query: str                   # Echo of the original ResearchQuery.query
    findings: str                # Assembled text of the retrieved content
    token_count_estimate: int    # len(findings) // 4 approximation
```

---

## Run Schemas (`run.py`)

### `RunStatus`

Type-safe enum for run lifecycle states used by the State Machine.

```python
class RunStatus(StrEnum):
    PLANNING   = "planning"    # Initial state after hermetic plan
    APPROVED   = "approved"    # After hermetic approve — ready for execution
    EXECUTING  = "executing"   # hermetic implement is running
    DONE       = "done"        # All batches succeeded
    FAILED     = "failed"      # A batch exhausted all retries
```

> `RunStatus` is implemented in Story 5.

---

## Token Budget Constants

Defined in `src/hermetic/data/etl/assembler.py`:

| Constant | Value | Usage |
|---|---|---|
| `PLANNING_BUDGET` | 150,000 tokens | Context budget for Planning and Review nodes |
| `IMPLEMENTATION_BUDGET` | 750,000 tokens | Context budget for Implementation nodes |

Token estimates use the approximation `len(text) // 4`.
