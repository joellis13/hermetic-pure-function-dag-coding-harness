# Contract Schemas

All schemas are strictly typed, serializable to JSON, and explicitly reference the target repository.

## A. `IssueContext` (Preloaded & Self-Contained)
```python
class CodeSnippet(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    content: str
    symbol_name: str | None = None
    repo_name: str | None = None

class ExternalDoc(BaseModel):
    url_or_id: str
    title: str
    content: str
    source_type: str

class IssueContext(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    repo_name: str
    repo_path: str
    base_branch: str
    issue_id: str
    title: str
    body: str
    author: str
    labels: list[str]
    comments: list[str]
    code_snippets: list[CodeSnippet]
    referenced_docs: list[ExternalDoc]
    user_clarifications: dict[str, str] = Field(default_factory=dict)
```

## B. `ImplementationPlan` & Interactive Refinement
```python
class TaskItem(BaseModel):
    task_id: str
    title: str
    instructions: str
    target_files: list[str]
    expected_outcome: str
    verification_command: str | None = None
    repo_name: str | None = None

class TaskBatch(BaseModel):
    batch_index: int
    name: str
    tasks: list[TaskItem]

class ImplementationPlan(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    repo_name: str
    repo_path: str
    base_branch: str
    working_branch: str
    issue_id: str
    summary: str
    architectural_notes: str
    acceptance_criteria: list[str]
    testing_strategy: str
    batches: list[TaskBatch]

class UserFeedback(BaseModel):
    iteration: int
    timestamp: str
    feedback_text: str

class PlanIterationContext(BaseModel):
    issue_context: IssueContext
    current_plan: ImplementationPlan
    critic_critique: str | None = None
    feedback_history: list[UserFeedback] = Field(default_factory=list)
```

## C. `TaskDeliverable` & `StructuredFileEdit`
```python
class SearchReplaceBlock(BaseModel):
    search_target: str
    replacement: str

class StructuredFileEdit(BaseModel):
    file_path: str
    action: Literal["CREATE", "MODIFY", "DELETE"]
    new_content: str | None = None
    blocks: list[SearchReplaceBlock] = Field(default_factory=list)

class TaskRetryContext(BaseModel):
    task_spec: TaskItem
    attempt_number: int
    failed_edits: list[StructuredFileEdit]
    validation_error_output: str
    previous_patch_diff: str | None = None

class TaskDeliverable(BaseModel):
    task_id: str
    status: Literal["SUCCESS", "FAILED", "SKIPPED"]
    repo_name: str | None = None
    structured_edits: list[StructuredFileEdit] = Field(default_factory=list)
    patch_diff: str = ""
    test_output: str | None = None
    retry_count: int = 0
    error_message: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

class FullImplementationReport(BaseModel):
    run_id: str
    repo_name: str
    repo_path: str
    issue_id: str
    branch_name: str
    overall_status: Literal["PASSED", "FAILED_VERIFICATION", "INCOMPLETE"]
    task_deliverables: list[TaskDeliverable]
    total_latency_ms: int
    token_usage_summary: dict[str, int]
```

## D. `ResearchDossier` & `ReviewReport`
```python
class ResearchDossier(BaseModel):
    topic: str
    repo_name: str
    objective: str
    findings: list[str]
    tradeoffs_analyzed: list[dict[str, str]]
    recommended_path: str
    open_questions: list[str]
    citations: list[str]

class ReviewFinding(BaseModel):
    severity: Literal["CRITICAL", "WARNING", "SUGGESTION"]
    file_path: str
    line_number: int | None
    comment: str
    suggested_fix: str | None

class ReviewReport(BaseModel):
    pr_id: str
    repo_name: str
    summary: str
    passed: bool
    findings: list[ReviewFinding]
    test_coverage_assessment: str
```
