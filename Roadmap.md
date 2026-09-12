# Project Roadmap

This document outlines planned features and architectural enhancements for the **Hermetic Pure-Function DAG AI Coding Harness** that fall outside the scope of the Phase 1 initial implementation.

## 1. Autonomous Context Assembly (Solving the Zero-Shot Discovery Problem)

**The Problem:**
Currently, the `IssueContext` is preloaded deterministically based on issue descriptions and user-supplied file paths. If a user provides a vague issue (e.g., "Fix the auth bug"), the Planning Node will not have the necessary source files in its context to formulate an accurate plan. Because AI nodes run hermetically without shell access, they cannot run `grep` or explore the codebase mid-plan.

**The Planned Solution:**
Introduce a **Research Micro-DAG** that executes *before* the Implementation Planning Micro-DAG.

1. **Research Node**: An LLM is given the raw issue description and the schema for `ContextRequest`.
2. **ContextRequest Schema**: Allows the LLM to request specific codebase lookups:
   - `search_regex`: e.g., "def login" or "class User"
   - `read_files`: e.g., ["src/auth.py", "tests/test_auth.py"]
   - `find_symbols`: e.g., "AuthService"
3. **Deterministic Retrieval**: The Data Plane executes these queries against the local repository and populates an immutable `ResearchDossier` or expands the `IssueContext`.
4. **Iterative Loop**: The Research DAG can loop up to N times until the LLM declares it has enough context to begin planning.
5. **Handoff**: The final, populated `IssueContext` is passed to the standard Planning Micro-DAG.

This keeps the system hermetic and bounded while giving the LLM the ability to "explore" the codebase safely and deterministically.

## 2. Advanced File Editing Capabilities (Fuzzy/AST Replacement)

**The Problem:**
In the Phase 1 MVP, SearchReplaceBlock relies on strict, exact-character string matching. While the 3-attempt retry loop and clear instructions usually resolve hallucinated whitespace or missed docstrings, relying on retries costs additional LLM tokens and execution time. 

**The Planned Solution:**
As the harness matures, we can introduce more resilient application mechanisms that preserve the deterministic boundary:
1. **Whitespace-Agnostic Matching**: The applier normalizes both the target file and the search_target (stripping leading/trailing lines, normalizing indent levels) to find the insertion point without demanding character-perfect whitespace from the LLM.
2. **AST-based Symbol Replacement**: Allowing the LLM to emit a eplace_symbol: "function_name" command. The deterministic harness parses the Python AST, finds the symbol boundaries, and replaces the block. This completely bypasses the need for the LLM to echo existing code.
