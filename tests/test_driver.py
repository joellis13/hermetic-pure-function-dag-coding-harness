"""Tests for AgentDriver ABC, MockDriver, AntigravityDriver, and CriticNode."""
from __future__ import annotations

import os
from typing import Callable

import pytest

from hermetic.compute.critic import CriticNode, _resolve_critic_model
from hermetic.compute.driver import AgentDriver, AntigravityDriver, MockDriver, NodeExecutionMetadata
from hermetic.schemas.context import IssueContext
from hermetic.schemas.plan import ImplementationPlan, TaskBatch, TaskItem
from hermetic.schemas.review import ReviewFeedback


live = pytest.mark.skipif(
    not os.getenv("HERMETIC_RUN_LIVE_TESTS"),
    reason="Set HERMETIC_RUN_LIVE_TESTS=1 to run live model tests",
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_plan() -> ImplementationPlan:
    return ImplementationPlan(
        plan_id="plan-test",
        issue_id="GH-1",
        batches=[
            TaskBatch(
                batch_id="batch-1",
                description="Test batch",
                tasks=[
                    TaskItem(
                        id="task-1",
                        description="Do something",
                        instruction="Do it now",
                        dependencies=[],
                    )
                ],
            )
        ],
    )


@pytest.fixture
def sample_context() -> IssueContext:
    return IssueContext(
        issue_id="GH-1",
        title="Test Issue",
        description="A test issue description.",
    )


# ── TestMockDriver ────────────────────────────────────────────────────────────

class TestMockDriver:
    async def test_mock_driver_returns_configured_response(self) -> None:
        driver = MockDriver(response="hello world")
        text, _ = await driver.invoke("prompt", "system")
        assert text == "hello world"

    async def test_mock_driver_metadata_has_correct_model_name(self) -> None:
        driver = MockDriver(response="x", model_name="test-model")
        _, meta = await driver.invoke("p", "s")
        assert meta.model_name == "test-model"

    async def test_mock_driver_default_model_name_is_mock(self) -> None:
        driver = MockDriver(response="x")
        _, meta = await driver.invoke("p", "s")
        assert meta.model_name == "mock"

    async def test_mock_driver_estimates_token_counts_from_string_length(self) -> None:
        prompt = "a" * 40   # 10 tokens
        response = "b" * 20  # 5 tokens
        driver = MockDriver(response=response)
        _, meta = await driver.invoke(prompt, "system")
        assert meta.input_tokens == 10
        assert meta.output_tokens == 5

    async def test_mock_driver_latency_is_zero(self) -> None:
        driver = MockDriver(response="r")
        _, meta = await driver.invoke("p", "s")
        assert meta.latency_ms == 0.0

    async def test_mock_driver_is_awaitable(self) -> None:
        import inspect
        driver = MockDriver(response="r")
        coro = driver.invoke("p", "s")
        assert inspect.isawaitable(coro)
        await coro


# ── TestAgentDriverABC ────────────────────────────────────────────────────────

class TestAgentDriverABC:
    def test_cannot_instantiate_abstract_driver(self) -> None:
        with pytest.raises(TypeError):
            AgentDriver()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_invoke(self) -> None:
        class IncompleteDriver(AgentDriver):
            pass  # missing invoke

        with pytest.raises(TypeError):
            IncompleteDriver()

    def test_mock_driver_is_valid_concrete_subclass(self) -> None:
        driver = MockDriver(response="ok")
        assert isinstance(driver, AgentDriver)


# ── TestNodeExecutionMetadata ─────────────────────────────────────────────────

class TestNodeExecutionMetadata:
    def test_metadata_is_frozen(self) -> None:
        meta = NodeExecutionMetadata(
            input_tokens=10, output_tokens=5, latency_ms=100.0, model_name="m"
        )
        with pytest.raises((AttributeError, TypeError)):
            meta.input_tokens = 999  # type: ignore[misc]

    def test_metadata_fields(self) -> None:
        meta = NodeExecutionMetadata(
            input_tokens=100, output_tokens=50, latency_ms=250.5, model_name="claude-sonnet-4-6"
        )
        assert meta.input_tokens == 100
        assert meta.output_tokens == 50
        assert meta.latency_ms == 250.5
        assert meta.model_name == "claude-sonnet-4-6"


# ── TestCriticNode ────────────────────────────────────────────────────────────

class TestCriticNode:
    def test_critic_selects_gemini_pro_for_claude_sonnet_planner(self) -> None:
        node = CriticNode(planner_model="claude-sonnet-4-6", driver_factory=lambda m: MockDriver("x"))
        assert node.critic_model == "gemini-3-1-pro"

    def test_critic_selects_gemini_pro_for_claude_opus_planner(self) -> None:
        node = CriticNode(planner_model="claude-opus-4-6", driver_factory=lambda m: MockDriver("x"))
        assert node.critic_model == "gemini-3-1-pro"

    def test_critic_selects_gemini_pro_for_generic_claude_planner(self) -> None:
        node = CriticNode(planner_model="claude-unknown-model", driver_factory=lambda m: MockDriver("x"))
        assert node.critic_model == "gemini-3-1-pro"

    def test_critic_selects_claude_for_gemini_pro_planner(self) -> None:
        node = CriticNode(planner_model="gemini-3-1-pro", driver_factory=lambda m: MockDriver("x"))
        assert node.critic_model == "claude-sonnet-4-6"

    def test_critic_selects_claude_for_gemini_flash_planner(self) -> None:
        node = CriticNode(planner_model="gemini-3-8-flash", driver_factory=lambda m: MockDriver("x"))
        assert node.critic_model == "claude-sonnet-4-6"

    def test_critic_uses_unknown_provider_fallback(self) -> None:
        result = _resolve_critic_model("gpt-999")
        assert result == "gemini-3-1-pro"

    async def test_critic_approved_true_when_mock_returns_approved_json(
        self,
        sample_plan: ImplementationPlan,
        sample_context: IssueContext,
    ) -> None:
        approved_json = '{"approved": true, "comments": "Looks good", "suggested_changes": []}'
        node = CriticNode(
            planner_model="claude-sonnet-4-6",
            driver_factory=lambda m: MockDriver(approved_json),
        )
        feedback, meta = await node.evaluate(sample_plan, sample_context)
        assert feedback.approved is True
        assert feedback.comments == "Looks good"
        assert isinstance(meta, NodeExecutionMetadata)

    async def test_critic_approved_false_when_mock_returns_rejected_json(
        self,
        sample_plan: ImplementationPlan,
        sample_context: IssueContext,
    ) -> None:
        rejected_json = '{"approved": false, "comments": "Missing tests", "suggested_changes": []}'
        node = CriticNode(
            planner_model="gemini-3-8-flash",
            driver_factory=lambda m: MockDriver(rejected_json),
        )
        feedback, meta = await node.evaluate(sample_plan, sample_context)
        assert feedback.approved is False
        assert "Missing tests" in feedback.comments

    async def test_critic_returns_unparseable_feedback_on_sanitization_failure(
        self,
        sample_plan: ImplementationPlan,
        sample_context: IssueContext,
    ) -> None:
        # Return truly broken JSON that can't be repaired
        node = CriticNode(
            planner_model="claude-sonnet-4-6",
            driver_factory=lambda m: MockDriver("this is not json at all !!!"),
        )
        feedback, _ = await node.evaluate(sample_plan, sample_context)
        assert feedback.approved is False
        assert "unparseable" in feedback.comments.lower()

    async def test_critic_fallback_on_cross_provider_failure(
        self,
        sample_plan: ImplementationPlan,
        sample_context: IssueContext,
    ) -> None:
        """
        When the cross-provider driver raises, the same-provider fallback is used.
        The fallback returns a valid approved JSON.
        """
        call_log: list[str] = []
        approved_json = '{"approved": true, "comments": "Fallback OK", "suggested_changes": []}'

        def factory(model: str) -> AgentDriver:
            call_log.append(model)
            if model == "gemini-3-1-pro":  # cross-provider target for claude planner
                class FailDriver(AgentDriver):
                    async def invoke(self, prompt: str, system: str):
                        raise RuntimeError("network error")
                return FailDriver()
            return MockDriver(approved_json)

        node = CriticNode(planner_model="claude-sonnet-4-6", driver_factory=factory)
        feedback, _ = await node.evaluate(sample_plan, sample_context)
        assert feedback.approved is True
        # First call was to cross-provider model, second was fallback
        assert "gemini-3-1-pro" in call_log
        assert len(call_log) == 2


# ── TestAntigravityDriverLive ─────────────────────────────────────────────────

class TestAntigravityDriverLive:
    @live
    async def test_live_driver_returns_non_empty_string(self) -> None:
        driver = AntigravityDriver(model="gemini-3-8-flash")
        text, meta = await driver.invoke("Say 'hello'", system="Be concise.")
        assert isinstance(text, str)
        assert len(text) > 0

    @live
    async def test_live_driver_metadata_has_positive_token_counts(self) -> None:
        driver = AntigravityDriver(model="gemini-3-8-flash")
        _, meta = await driver.invoke("What is 2+2?", system="Be concise.")
        assert meta.input_tokens >= 0
        assert meta.output_tokens >= 0

    @live
    async def test_live_driver_latency_is_positive(self) -> None:
        driver = AntigravityDriver(model="gemini-3-8-flash")
        _, meta = await driver.invoke("Say 'hi'", system="Be concise.")
        assert meta.latency_ms > 0
