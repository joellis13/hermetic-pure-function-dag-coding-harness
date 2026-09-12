# ADR 0002: Structured File Edits vs. Raw Git Diffs

## Context
A critical boundary must be maintained between probabilistic model synthesis and deterministic software engineering.

## Decision
* **The Probabilistic Boundary (Model Synthesis)**:
  - Models emit intent strictly through the `StructuredFileEdit` schema (`CREATE`, `MODIFY` with `SearchReplaceBlock`, `DELETE`).
  - Models are not asked to emit raw unified diffs, as they are notoriously bad at line-offset arithmetic and hunk headers.
* **The Deterministic Boundary (Harness Execution)**:
  - **Target Verification**: Validates `search_target` uniqueness via exact-string matching.
  - **Directory/File Creation**: Uses native `pathlib.Path.mkdir(parents=True)`.
  - **Formatting**: Runs local formatters.
  - **Canonical Diff Generation**: Runs `git diff` via subprocess to calculate the syntactically pristine unified diff for reporting.
