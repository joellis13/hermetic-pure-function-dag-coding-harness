# Hermetic Pure-Function DAG AI Coding Harness

The **Hermetic Pure-Function DAG AI Coding Harness** (`hermetic`) is an AI-powered coding pipeline built on a strict separation of concerns:

- **Deterministic tasks** — data fetching, schema validation, git operations, linting, and testing — run hermetically and predictably in ordinary Python code.
- **AI tasks** — planning, code generation, and cross-provider critique — run as bounded, stateless pure-function nodes that receive a typed schema in and return a typed schema out.

LLMs are treated as **bounded, mockable functions**:

| Boundary | Details |
|---|---|
| **Input** | Immutable `IssueContext` — issue body, code snippets, external docs |
| **Compute** | `AgentDriver.invoke(prompt, system)` — async, swappable backend |
| **Output** | Pydantic-validated `ImplementationPlan` or `TaskDeliverable` |

---

## Getting Started

### Prerequisites

| Tool | Version | Notes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.4 | `pip install uv` or `winget install astral-sh.uv` |
| Python | 3.13 | Downloaded automatically by `uv` — do not install manually |
| Git | any recent | Required for worktree isolation |
| Google Antigravity | subscription | Powers `AntigravityDriver` for live AI calls |

### Installation

```powershell
# Clone and enter the repo
git clone https://github.com/<owner>/hermetic-pure-function-dag-coding-harness
cd hermetic-pure-function-dag-coding-harness

# Install all dependencies into an isolated .venv
uv sync

# Verify
uv run hermetic --help
```

### Run the Test Suite

```powershell
# All unit and integration tests — no network required, ~6 seconds
uv run pytest tests/ -v

# Expected: 155 passed, 3 skipped  (live-only tests are auto-skipped)
```

See [docs/getting-started.md](docs/getting-started.md) for a full walkthrough including environment setup, first run, and troubleshooting.

---

## Usage

> **Note:** The `plan`, `review`, and `approve` CLI commands are implemented in Story 5. During Stories 1–4, only the Python API and test suite are active.

```powershell
# Set credentials
$env:GITHUB_TOKEN = "ghp_..."

# Generate an implementation plan for GitHub issue #42
uv run hermetic plan 42 --owner myorg --github-repo my-repo --repo .

# Optionally refine interactively
uv run hermetic review <run-id>

# Approve and prepare for execution
uv run hermetic approve <run-id>

# Execute the approved plan (Story 6)
uv run hermetic implement <run-id>
```

See [docs/cli.md](docs/cli.md) for the full CLI reference.

---

## Documentation

| Doc | Description |
|---|---|
| [Getting Started](docs/getting-started.md) | Full setup walkthrough, first run, troubleshooting |
| [Architecture & Workflows](docs/architecture.md) | System design, plane separation, sequence diagrams |
| [Schema Reference](docs/schemas.md) | All Pydantic contracts with field descriptions |
| [CLI Reference](docs/cli.md) | All commands, options, and environment variables |
| [ADR 0001: Ephemeral Git Worktrees](docs/adr/0001-ephemeral-git-worktrees.md) | Why git worktrees, not Docker |
| [ADR 0002: Structured File Edits](docs/adr/0002-structured-file-edits.md) | Why search/replace, not raw diffs |
| [ADR 0003: Stateless HITL Refinement](docs/adr/0003-stateless-hitl-refinement.md) | Pure-function iteration over conversational transcripts |
| [ADR 0004: Two-Tier JSON Sanitization](docs/adr/0004-two-tier-json-sanitization.md) | Fence stripping + trailing-comma repair |

---

## Project Layout

```text
hermetic-pure-function-dag-coding-harness/
├── pyproject.toml              # Dependencies & metadata (uv managed)
├── uv.lock                     # Deterministic lockfile
├── .python-version             # Pinned to Python 3.13
├── src/
│   └── hermetic/
│       ├── cli/                # Typer/Rich CLI commands
│       ├── client/             # External clients (GitHub GraphQL)
│       ├── control/            # DAG engine + SQLite state machine
│       ├── compute/            # AI nodes: AgentDriver, PlanningNode, CriticNode
│       ├── data/               # Data plane: cache, sanitizer, worktree, ETL, renderer
│       └── schemas/            # Pydantic contracts (IssueContext, ImplementationPlan, …)
├── tests/
│   ├── fixtures/               # Hardcoded JSON fixtures for reproducible tests
│   └── test_*.py               # Unit + integration tests
├── docs/
│   ├── architecture.md         # System design & workflow sequence diagrams
│   ├── schemas.md              # Pydantic contract reference
│   ├── getting-started.md      # Detailed setup & first-run walkthrough
│   ├── cli.md                  # CLI command reference
│   └── adr/                    # Architecture Decision Records
└── .harness/                   # Runtime data (gitignored)
    ├── state.db                # SQLite run state & versioned plan checkpoints
    ├── worktrees/              # Ephemeral git worktrees (auto-pruned)
    └── runs/                   # Per-run artifacts (plan.html, full_report.html)
```

---

## Development & Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the local dev environment setup guide.

## Project Planning

- **[Implementation Plan](ImplementationPlan.md)** — Phase 0 to 1e MVP tasks.
- **[Roadmap](Roadmap.md)** — Future features: Autonomous Context Assembly, DirectDriver, Cost tracking, Jira/Confluence, Multi-repo.
