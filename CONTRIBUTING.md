# Contributing

## Python Version & Environment

* **Target Version: Python 3.13**
  * *Why 3.13*: Full Pydantic v2 support, 100% precompiled binary wheel availability on Windows (same as 3.12), meaningfully improved error messages, and a faster interactive REPL. The experimental JIT and free-threading flags are disabled by default — no risk, only upside. Python 3.14 is avoided due to Rust/Pydantic binary wheel build issues.
  * Running `uv python pin 3.13` instructs `uv` to download and isolate a dedicated Python 3.13 runtime, bypassing host PATH versions.
* **100% `uv` Project Management**:
  * Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.
  * Commands run seamlessly: `uv run hermetic ...`.
  * Eliminates global package contamination and manual virtualenv activation.

## Project Directory Layout

```text
hermetic-pure-function-dag-coding-harness/
├── pyproject.toml              # Dependencies & metadata (uv managed)
├── uv.lock                     # Deterministic dependency lockfile
├── .python-version             # Pinned to 3.12 (via uv)
├── README.md                   # Quickstart and overview
├── CONTRIBUTING.md             # This document
├── docs/                       # Architecture, schemas, and ADRs
├── .gitignore                  # Excludes .harness/ and .python-version
├── .harness/                   # Local runtime data (gitignored)
│   ├── state.db                # SQLite run state & checkpoints
│   ├── cache/                  # Content-addressable cache entries
│   ├── worktrees/              # Ephemeral git worktrees
│   └── runs/                   # Structured run artifacts by workflow
├── src/
│   └── hermetic/
│       ├── __init__.py
│       ├── cli/                # Command-line interface (Typer/Rich)
│       ├── control/            # Control Plane (DAG engine, state machine)
│       ├── data/               # Data Plane (Git manager, ETL, renderer)
│       ├── compute/            # AI Compute & Adapters (Agent driver, sanitizer)
│       └── schemas/            # Pydantic Contract Schemas
└── tests/                      # Unit and integration tests
```
