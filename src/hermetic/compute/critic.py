"""CriticNode: cross-provider evaluation of ImplementationPlan."""
from __future__ import annotations

import json
from typing import Callable

from hermetic.compute.driver import AgentDriver, NodeExecutionMetadata
from hermetic.data.sanitizer import SanitizationError, sanitize_json
from hermetic.schemas.context import IssueContext
from hermetic.schemas.plan import ImplementationPlan
from hermetic.schemas.review import ReviewFeedback

# Cross-provider model map: planner model prefix → critic model.
#
# Tier alignment is intentional:
#   - Sonnet/Opus → Gemini 3.1 Pro  (same or closest tier, different provider)
#   - Gemini Pro  → Claude Sonnet   (same tier)
#   - Gemini Flash → Claude Sonnet  (deliberate uplift — critic must outgun a fast/cheap planner)
#
# Keys are matched via `startswith` against the lowercased planner model string,
# checked longest-prefix first to allow per-model overrides.
_CROSS_PROVIDER_MAP: dict[str, str] = {
    "claude-opus": "gemini-3-1-pro",      # Opus → best available Gemini
    "claude-sonnet": "gemini-3-1-pro",    # Sonnet → Pro (tier-matched)
    "claude": "gemini-3-1-pro",           # any other Claude → Pro (safe default)
    "gemini-3-1-pro": "claude-sonnet-4-6",  # Pro → Sonnet (tier-matched)
    "gemini": "claude-sonnet-4-6",        # any Gemini Flash/other → Sonnet (uplift)
}

# Same-provider adversarial fallback (only used if cross-provider call fails).
_SAME_PROVIDER_FALLBACK: dict[str, str] = {
    "claude": "claude-sonnet-4-6",
    "gemini": "gemini-3-1-pro",
}


def _resolve_critic_model(planner_model: str) -> str:
    """Return the cross-provider critic model given the planner model name.

    Uses longest-prefix matching so 'claude-sonnet' beats the generic 'claude' key.
    """
    lower = planner_model.lower()
    # Sort by key length descending so specific prefixes win over generic ones
    for prefix in sorted(_CROSS_PROVIDER_MAP, key=len, reverse=True):
        if lower.startswith(prefix):
            return _CROSS_PROVIDER_MAP[prefix]
    # Unknown provider: default to gemini-3-1-pro for maximum critic quality
    return "gemini-3-1-pro"


def _resolve_same_provider_fallback(planner_model: str) -> str:
    """Return same-provider fallback model when cross-provider fails."""
    lower = planner_model.lower()
    for prefix in sorted(_SAME_PROVIDER_FALLBACK, key=len, reverse=True):
        if lower.startswith(prefix):
            return _SAME_PROVIDER_FALLBACK[prefix]
    return "gemini-3-1-pro"


def _build_critic_prompt(plan: ImplementationPlan, context: IssueContext) -> str:
    """Build the evaluation prompt for the critic."""
    return (
        f"Issue: {context.issue_id} — {context.title}\n\n"
        f"Description:\n{context.description}\n\n"
        f"Plan to review (JSON):\n{plan.model_dump_json(indent=2)}"
    )


_CRITIC_SYSTEM_PROMPT: str = (
    "You are a rigorous, adversarial code review critic.\n"
    "Your job is to evaluate an ImplementationPlan produced by another AI model and identify weaknesses.\n"
    "Be skeptical. Flag missing tests, unhandled edge cases, under-specified instructions, and security issues.\n\n"
    "Return ONLY valid JSON matching this schema (no prose before or after):\n"
    + json.dumps(ReviewFeedback.model_json_schema(), indent=2)
)


class CriticNode:
    """Evaluates an ImplementationPlan using a cross-provider model.

    Returns a ReviewFeedback schema.
    """

    def __init__(self, planner_model: str, driver_factory: Callable[[str], AgentDriver]) -> None:
        """
        Args:
            planner_model: The model string used by the Planner (e.g. "claude-sonnet-4-6").
            driver_factory: A callable that takes a model string and returns an AgentDriver.
                            Use `lambda m: AntigravityDriver(m)` in production,
                            `lambda m: MockDriver(...)` in tests.
        """
        self._planner_model = planner_model
        self._driver_factory = driver_factory
        self._critic_model = _resolve_critic_model(planner_model)

    @property
    def critic_model(self) -> str:
        """The resolved critic model string."""
        return self._critic_model

    async def evaluate(
        self,
        plan: ImplementationPlan,
        context: IssueContext,
    ) -> tuple[ReviewFeedback, NodeExecutionMetadata]:
        """Evaluate the plan. Tries cross-provider first; falls back to same-provider
        adversarial persona if cross-provider raises an exception.
        """
        driver = self._driver_factory(self._critic_model)
        prompt = _build_critic_prompt(plan, context)
        system = _CRITIC_SYSTEM_PROMPT
        try:
            raw, meta = await driver.invoke(prompt, system)
        except Exception:
            # Cross-provider failed: fall back to same-provider adversarial model
            fallback = _resolve_same_provider_fallback(self._planner_model)
            driver = self._driver_factory(fallback)
            raw, meta = await driver.invoke(prompt, system)

        clean = sanitize_json(raw)
        if isinstance(clean, SanitizationError):
            return ReviewFeedback(
                approved=False,
                comments=f"Critic output unparseable: {clean.error_message}",
            ), meta

        try:
            feedback = ReviewFeedback.model_validate_json(clean)
        except Exception as exc:
            return ReviewFeedback(
                approved=False,
                comments=f"Critic output unparseable: {exc}",
            ), meta

        return feedback, meta
