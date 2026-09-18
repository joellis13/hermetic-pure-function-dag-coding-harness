"""Self-hosting planning test using real live AI drivers."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermetic.compute.critic import CriticNode
from hermetic.compute.driver import AntigravityDriver
from hermetic.compute.planning_node import PlanningNode
from hermetic.data.etl.assembler import ContextAssembler
from hermetic.data.renderer import render_plan_html, write_html
from hermetic.schemas.plan import ImplementationPlan


live = pytest.mark.skipif(
    not os.getenv("HERMETIC_RUN_LIVE_TESTS"),
    reason="Set HERMETIC_RUN_LIVE_TESTS=1 to run self-hosting planning test",
)


class TestSelfHostingPlan:
    @live
    async def test_self_hosting_plan_generation(self, tmp_path: Path) -> None:
        """
        Self-hosting smoke test: IssueContext built from local files via ContextAssembler
        (no GitHub fetch). Uses real AntigravityDriver + CriticNode.
        Asserts: valid ImplementationPlan produced, plan.html renders without error.
        """
        repo_root = Path(__file__).resolve().parent.parent
        assembler = ContextAssembler(repo_root=repo_root)

        context, _ = assembler.assemble(
            issue_id="SELF-HOST-1",
            title="Implement Self-Hosting Planning Enhancements",
            description="Extend the hermetic planning node to support autonomous self-hosting workflows.",
            file_paths=["src/hermetic/schemas/plan.py", "src/hermetic/compute/planning_node.py"],
            doc_urls_and_content=[],
        )

        model = os.getenv("HERMETIC_LIVE_MODEL", "gemini-3-8-flash")
        driver = AntigravityDriver(model=model)
        planner = PlanningNode(driver=driver)

        plan, meta = await planner.plan(context)
        assert isinstance(plan, ImplementationPlan)
        assert plan.issue_id == context.issue_id
        assert len(plan.batches) >= 1
        assert meta.output_tokens > 0

        critic = CriticNode(
            planner_model=model,
            driver_factory=lambda m: AntigravityDriver(m),
        )
        feedback, critic_meta = await critic.evaluate(plan, context)
        assert isinstance(feedback.approved, bool)
        assert len(feedback.comments) > 0

        html = render_plan_html(plan, context=context)
        out_path = tmp_path / "plan.html"
        write_html(html, out_path)

        assert out_path.exists()
        assert "SELF-HOST-1" in out_path.read_text(encoding="utf-8")
