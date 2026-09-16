# System Architecture & Extensibility

The system is organized into two primary planes and an orchestration model:

```mermaid
flowchart TD
    subgraph ControlPlane["Control Plane (State Machine Orchestrator)"]
        SM["Control Plane State Machine"]
        SM -->|Dispatches| PlanDAG["1. Planning Micro-DAG"]
        SM -->|Dispatches| ExecDAG["2. Implementation Micro-DAG"]
        SM -->|Dispatches| ReviewDAG["3. Review / Refine Micro-DAG"]
        SM --> StateStore["Local State & Run Checkpoints (SQLite)"]
        SM --> Telemetry["Telemetry & Metrics Aggregator"]
    end

    subgraph DataPlane["Data Plane (Layered Clean Architecture)"]
        Client["Clients (GitHub, Jira, Confluence, Local Git)"]
        Repo["Repositories & File Parsers"]
        Adapter["Adapters & AST/Symbol Grounding"]
        ETL["ETL & Context Assembler (Budget & Cycle Guard)"]
        Renderer["HTML/Markdown Report Renderer"]
        Client --> Repo --> Adapter --> ETL
        ETL --> Renderer
    end

    subgraph PureCompute["AI Compute Nodes"]
        AgentDriver["Unified Agent Driver (Antigravity / Copilot / Direct Models)"]
        Cache["Content-Addressable Local Cache (SHA256)"]
        Critic["Rubber Duck / Critic Node (Cross-Provider)"]
        AgentDriver <--> Cache
        AgentDriver --> Critic
    end

    PlanDAG --> DataPlane
    PlanDAG --> PureCompute
    ExecDAG --> PureCompute
```

## A. Control Plane (State Machine over Micro-DAGs)
* **Architecture Pattern**: State Machine orchestrating focused, acyclic Micro-DAGs (`Intake` -> `Planning` -> `Critic / Rubber Duck` -> `Interactive HITL Review` -> `Batch Execution` -> `Verification` -> `Final Delivery`).
* **State & Checkpoints**: Powered by local SQLite (`.harness/state.db`). Supports full suspension and resumption (e.g., waiting for human review or recovering from a transient failure).
* **Interactive HITL Refinement**: The user can converse, critique, or directly edit the plan. Every feedback turn triggers a functional state transition yielding a versioned checkpoint.
* **Telemetry & Metrics**: Every node execution returns a `NodeExecutionMetadata` record. The Control Plane natively aggregates these into run summaries.
* **Hermetic Isolation**: All code generation occurs on dedicated Git branches in sandboxed ephemeral `git worktree` instances.

## B. Data Plane (Deterministic & Extensible Layers)
Structured using clean architecture layers:
1. `client`: Native HTTP/GraphQL clients for issue trackers and doc systems.
2. `repository`: Local filesystem and local Git repository access, including ephemeral worktrees.
3. `adapter`: Normalizers that transform external payloads into unified internal representations.
4. `indexer`: Deterministic codebase grounding (symbol resolution via regex/AST/ripgrep).
5. `etl`: Aggregates and validates data into self-contained context schemas with strict token budget enforcement.
6. `renderer`: Automatically renders human-readable HTML previews from JSON schemas.

## C. Pure Compute Plane & Unified Agent Driver
Regardless of the backend (Direct Model APIs, Antigravity, or Copilot), all AI node executions are **stateless, non-interactive invocations with evolving supporting context**.

**Invocation Model**: The `AntigravityDriver` uses the `google-antigravity` Python SDK (`google.antigravity.Agent` + `LocalAgentConfig`) via native `async/await`. This integrates cleanly with `asyncio.TaskGroup`, exposes structured `usage_metadata` for token counts and latency, and is fully mockable in tests via the `AgentDriver` ABC. Shell-out to the `agy` CLI is explicitly rejected.

**Default Model Tiers**:
- **Claude Sonnet**: Research, Planning, and Review nodes (long-context reasoning, architectural synthesis, critique).
- **Gemini Flash**: Implementation Task nodes (speed and cost efficiency for mechanical code generation from well-specified `TaskItem` instructions).

**Cross-Provider Critic (Hard Requirement)**: The Critic Node **must** use a model from a different provider than the Planner. If the Planner runs on Claude Sonnet, the Critic runs on a Gemini model (and vice versa). This prevents both nodes from sharing training blind spots. A same-provider adversarial-persona prompt is only acceptable as a fallback when the cross-provider call fails.

---

# Workflows & Standard Operating Procedures

## Workflow 1: Implementation Planning, Critic, & Interactive HITL

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CP as Control Plane (State Machine)
    participant DP as Data Plane (ETL & AST)
    participant Cache as Content-Addressable Cache
    participant LLM as Planning Agent (Reasoning Tier)
    participant Duck as Rubber Duck Agent (Critic Tier)
    participant Rend as HTML Renderer
    participant Store as Local Storage (SQLite)

    User->>CP: hermetic plan --issue 104 --repo ../my-target-repo
    CP->>DP: Fetch Issue & Linked Resources (GitHub GraphQL + Local Git)
    DP->>DP: Ground Symbols & Assemble IssueContext (apply token budget)
    DP-->>CP: IssueContext (immutable)
    CP->>Cache: Check SHA256(IssueContext + Prompt + Model)
    alt Cache Hit
        Cache-->>CP: Cached ImplementationPlan
    else Cache Miss
        CP->>LLM: Generate Draft Plan (TIER_REASONING)
        LLM-->>CP: Draft ImplementationPlan
        CP->>Duck: Review Plan (TIER_CRITIC)
        Duck-->>CP: Critique & Refinements
        CP->>LLM: Finalize Plan with Critique
        LLM-->>CP: Final ImplementationPlan (Pydantic validated)
        CP->>Cache: Save to local cache
    end
    CP->>Rend: Render plan.html from plan.json
    Rend-->>CP: plan.html generated
    CP->>Store: Persist state, execution metadata & plan_v1.json
    CP->>User: Display summary + HTML link. Suspend state (WAITING_APPROVAL)

    loop Interactive HITL Refinement (Optional Back-and-Forth)
        User->>CP: hermetic review <run-id> (Feedback prompt or direct plan.json edit)
        CP->>LLM: Refine Plan (PlanIterationContext: IssueContext + CurrentPlan + UserFeedback)
        LLM-->>CP: Revised ImplementationPlan
        CP->>Rend: Re-render plan.html
        CP->>Store: Save versioned checkpoint (plan_vN.json)
        CP->>User: Display updated summary & diff
    end
    User->>CP: hermetic approve <run-id>
    CP->>Store: Transition state to APPROVED
```

## Workflow 2: Batch Execution & Ephemeral Worktree Verification

```mermaid
sequenceDiagram
    autonumber
    participant CP as Control Plane
    participant Git as Git Worktree Manager
    participant LLM as Task Agent (Fast Tier)
    participant Val as Deterministic Validator (Lint/Test)
    participant Rend as HTML Renderer

    CP->>Git: Ensure working branch 'harness/issue-104' exists in target repo
    loop For Each Batch in ImplementationPlan (Sequential)
        par For Each Task in Batch (Parallel in Ephemeral Worktrees)
            CP->>Git: Create isolated git worktree (.harness/worktrees/task-ID)
            CP->>LLM: Invoke with TaskSpec + Targeted Code Snippets
            LLM-->>CP: Structured File Edits (CREATE, MODIFY, DELETE)
            CP->>Git: Apply structured edits inside task worktree
            CP->>Val: Run Linters & Tests inside task worktree
            alt Validation Passed
                Val-->>CP: Green -> Deterministic git commit in worktree
            else Validation Failed (Max 3 retries)
                loop Retry up to 3 times
                    CP->>LLM: Refine with TaskRetryContext (errors + previous edits)
                    LLM-->>CP: Updated Structured File Edits
                    CP->>Git: Apply updated edits in worktree
                    CP->>Val: Re-run Linters & Tests
                end
            end
            CP->>Git: Compute canonical git diff & merge worktree into 'harness/issue-104'
            CP->>Git: Prune temporary worktree
            CP-->>CP: Record TaskDeliverable + Telemetry
        end
    end
    CP->>CP: Aggregate TaskDeliverables & Token Metadata
    CP->>Rend: Render full_report.html
    CP->>Git: Print final branch status and diff summary for user
```
