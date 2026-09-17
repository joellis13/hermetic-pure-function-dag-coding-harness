"""Walking Skeleton integration test — full pipeline with zero network calls."""
from __future__ import annotations

from pathlib import Path

import pytest

from hermetic.compute.driver import MockDriver
from hermetic.data.renderer import render_plan_html, write_html
from hermetic.data.sanitizer import SanitizationError, sanitize_json
from hermetic.schemas.context import IssueContext
from hermetic.schemas.plan import ImplementationPlan


class TestWalkingSkeleton:
    async def test_walking_skeleton_end_to_end(self, tmp_path: Path) -> None:
        """Full pipeline smoke test:
        IssueContext (JSON fixture) → MockDriver → ImplementationPlan → plan.html

        No network calls. Fully deterministic.
        """
        fixture_dir = Path(__file__).parent / "fixtures"

        # 1. Load the hardcoded IssueContext fixture
        context = IssueContext.model_validate_json(
            (fixture_dir / "issue_context.json").read_text(encoding="utf-8")
        )

        # 2. Load the deterministic plan JSON that MockDriver will return
        plan_json = (fixture_dir / "plan_response.json").read_text(encoding="utf-8")

        # 3. Build a MockDriver that returns the fixed plan JSON
        driver = MockDriver(response=plan_json)

        # 4. Invoke the driver (simulating what PlanningNode will do in Story 5)
        raw_text, meta = await driver.invoke(
            prompt=f"Plan implementation for: {context.title}",
            system="You are a planning assistant. Return a valid ImplementationPlan JSON.",
        )

        # 5. Sanitize and parse the response
        clean = sanitize_json(raw_text)
        assert not isinstance(clean, SanitizationError), (
            f"Sanitization failed: {clean.error_message}"
        )
        plan = ImplementationPlan.model_validate_json(clean)

        # 6. Verify plan structure
        assert plan.plan_id == "plan-walking-skeleton"
        assert plan.issue_id == context.issue_id
        assert len(plan.batches) >= 1

        # 7. Verify metadata
        assert meta.model_name == "mock"
        assert meta.output_tokens > 0

        # 8. Render plan.html and write to tmp_path
        html = render_plan_html(plan, context=context)
        out_path = tmp_path / "plan.html"
        write_html(html, out_path)

        # 9. Verify the output
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "plan-walking-skeleton" in content
        assert context.title in content
        assert "GH-1" in content
