# Hermetic Pure-Function DAG AI Coding Harness

The **Hermetic Pure-Function DAG AI Coding Harness** is a code generation and software engineering harness built on a foundational separation of concerns:
* **Deterministic tasks** (data fetching, parsing, repo indexing, AST analysis, schema validation, linting, testing, and git operations) are executed hermetically, idempotently, and predictably by traditional software engineering components.
* **Probabilistic AI models (LLMs)** are invoked exclusively for tasks requiring judgement, synthesis, planning, code generation, and critical review.

LLMs are treated as **pure-ish, bounded functions** inside execution nodes:
* **Strict Input**: An immutable, self-contained, typed schema containing all necessary code snippets, issue details, and documentation.
* **Bounded Compute**: Prompt template, system instructions, temperature `0.0`, and assigned model tier.
* **Strict Output**: A strictly validated deliverable schema.

## Documentation

The detailed technical specifications and design rationale are organized in the `docs/` directory:

* **[Architecture & Workflows](docs/architecture.md)**: System design (Control Plane, Data Plane, Compute Plane) and sequence diagrams for planning and execution.
* **[Data Schemas](docs/schemas.md)**: The strict Pydantic contracts used for inter-node communication.
* **[Architecture Decision Records (ADRs)](docs/adr/)**: Deep dives into the technical decisions, including:
  * [0001: Ephemeral Git Worktrees](docs/adr/0001-ephemeral-git-worktrees.md)
  * [0002: Structured File Edits vs. Raw Diffs](docs/adr/0002-structured-file-edits.md)
  * [0003: Stateless HITL Refinement](docs/adr/0003-stateless-hitl-refinement.md)
  * [0004: Two-Tier JSON Sanitization](docs/adr/0004-two-tier-json-sanitization.md)

## Development & Contributing

Please see **[CONTRIBUTING.md](CONTRIBUTING.md)** for instructions on setting up the local development environment (using Python 3.12 and `uv`) and the project directory layout.

## Project Planning

* **[Implementation Plan](ImplementationPlan.md)**: Phase 0 to 1e MVP and dogfooding tasks.
* **[Roadmap](Roadmap.md)**: Future features (Context Assembly, DirectDriver, Cost tracking, etc.).
