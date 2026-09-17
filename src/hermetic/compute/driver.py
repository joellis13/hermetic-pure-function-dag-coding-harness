"""AgentDriver ABC and concrete implementations (AntigravityDriver, MockDriver)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import time

from google.antigravity import Agent, LocalAgentConfig


@dataclass(frozen=True)
class NodeExecutionMetadata:
    """Execution metadata captured from an AI model invocation."""
    input_tokens: int      # from UsageMetadata.prompt_token_count
    output_tokens: int     # from UsageMetadata.candidates_token_count
    latency_ms: float      # wall-clock time of the await agent.chat() call
    model_name: str        # model string used, e.g. "claude-sonnet-4-6"


class AgentDriver(ABC):
    """Abstract base class for AI compute model drivers."""

    @abstractmethod
    async def invoke(
        self,
        prompt: str,
        system: str,
    ) -> tuple[str, NodeExecutionMetadata]:
        """Call the AI model. Returns (raw_text_response, metadata)."""


class AntigravityDriver(AgentDriver):
    """Production driver wrapping Google Antigravity Agent."""

    def __init__(self, model: str, *, api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key

    async def invoke(
        self,
        prompt: str,
        system: str,
    ) -> tuple[str, NodeExecutionMetadata]:
        config = LocalAgentConfig(
            model=self._model,
            system_instructions=system,
            api_key=self._api_key,
        )
        agent = Agent(config)
        t0 = time.monotonic()
        if hasattr(agent, "__aenter__"):
            async with agent:
                response = await agent.chat(prompt)
                text = await response.text()
                usage = response.usage_metadata
        else:
            response = await agent.chat(prompt)
            text = await response.text()
            usage = getattr(response, "usage_metadata", None)
        latency_ms = (time.monotonic() - t0) * 1000.0
        return text, NodeExecutionMetadata(
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
            latency_ms=latency_ms,
            model_name=self._model,
        )


class MockDriver(AgentDriver):
    """Deterministic, zero-network driver for use in tests and the Walking Skeleton."""

    def __init__(self, response: str, *, model_name: str = "mock") -> None:
        self._response = response
        self._model_name = model_name

    async def invoke(
        self,
        prompt: str,
        system: str,
    ) -> tuple[str, NodeExecutionMetadata]:
        return self._response, NodeExecutionMetadata(
            input_tokens=len(prompt) // 4,
            output_tokens=len(self._response) // 4,
            latency_ms=0.0,
            model_name=self._model_name,
        )
