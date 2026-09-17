"""
JSON Sanitizer — Tier-1 defense for raw LLM output.

Usage:
    result = sanitize_json(raw_llm_output)
    if isinstance(result, SanitizationError):
        # feed result.raw_text + result.error_message back to the model
        ...
    else:
        plan = ImplementationPlan.model_validate_json(result)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


# Matches an opening ```json or ``` fence and its closing ```
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# Trailing commas before } or ] — the single most common LLM JSON error
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


@dataclass(frozen=True)
class SanitizationError:
    """Returned when tier-1 repairs are insufficient and json.loads still fails."""
    raw_text: str
    error_message: str
    repaired_text: str  # The partially-repaired string, useful for debugging


def sanitize_json(raw_output: str) -> str | SanitizationError:
    """
    Apply tier-1 JSON repairs to `raw_output` and return the cleaned string.

    Returns:
        str: A string that successfully parses with json.loads().
        SanitizationError: If the text still cannot be parsed after repairs.
    """
    text = raw_output.strip()

    # Step 1: Extract content from markdown fences if present
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Step 2: Strip leading/trailing prose outside the root JSON structure.
    # Handles arrays enclosing objects, objects enclosing arrays, and prose
    # containing citation brackets or braces.
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")

    has_braces = first_brace != -1 and last_brace > first_brace
    has_brackets = first_bracket != -1 and last_bracket > first_bracket

    if has_braces and has_brackets:
        if first_bracket < first_brace and last_bracket > last_brace:
            # Array enclosing object(s): [{...}]
            text = text[first_bracket : last_bracket + 1]
        elif first_brace < first_bracket and last_brace > last_bracket:
            # Object enclosing array(s): {"key": [...]}
            text = text[first_brace : last_brace + 1]
        elif first_bracket < first_brace and first_brace > last_bracket:
            # Prose bracket citation before JSON object: "See note [1]: {...}"
            text = text[first_brace : last_brace + 1]
        elif first_brace < first_bracket and first_bracket > last_brace:
            # Prose placeholder brace before JSON array: "Using {name}: [...]"
            text = text[first_bracket : last_bracket + 1]
        else:
            # Sibling or ambiguous: pick whichever opened first
            if first_brace < first_bracket:
                text = text[first_brace : last_brace + 1]
            else:
                text = text[first_bracket : last_bracket + 1]
    elif has_braces:
        text = text[first_brace : last_brace + 1]
    elif has_brackets:
        text = text[first_bracket : last_bracket + 1]

    # Step 3: Strip trailing commas
    text = _TRAILING_COMMA_RE.sub(r"\1", text)

    # Step 4: Validate — return the cleaned string or a SanitizationError
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError as exc:
        return SanitizationError(
            raw_text=raw_output,
            error_message=str(exc),
            repaired_text=text,
        )
