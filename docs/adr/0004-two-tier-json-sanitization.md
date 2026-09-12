# ADR 0004: Two-Tier JSON Sanitization

## Context
Even with API-level JSON mode, models occasionally include markdown wrappers, trailing commas, or control characters, which break native JSON parsers.

## Decision
We employ a two-tier defense mechanism to guarantee deterministic parsing:
1. **Deterministic Sanitizer (`sanitizer.py`)**:
   - Strips markdown code fences (````json ... ````).
   - Trims conversational preambles/postscripts.
   - Normalizes trailing commas (`[1, 2,]` -> `[1, 2]`) using fast regex passes.
2. **Pydantic Validation**:
   - Parses the cleaned string into a validated Pydantic model.
   - If validation fails, the Pydantic error details are automatically structured into a zero-shot repair prompt for self-healing.
