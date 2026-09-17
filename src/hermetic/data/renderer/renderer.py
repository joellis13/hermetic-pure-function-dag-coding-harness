"""
HTML Renderer — pure functions for rendering ImplementationPlan and FullImplementationReport to standalone HTML.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from hermetic.schemas.context import IssueContext
from hermetic.schemas.deliverable import FullImplementationReport
from hermetic.schemas.plan import ImplementationPlan

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(
            enabled_extensions=("html", "htm", "j2"),
            default_for_string=True,
            default=True,
        ),
    )


def render_plan_html(plan: ImplementationPlan, context: IssueContext | None = None) -> str:
    """Render an ImplementationPlan to a standalone HTML string."""
    return _env().get_template("plan.html.j2").render(plan=plan, context=context)


def render_report_html(report: FullImplementationReport) -> str:
    """Render a FullImplementationReport to a standalone HTML string."""
    return _env().get_template("full_report.html.j2").render(report=report)


def write_html(content: str, output_path: Path) -> None:
    """Write an HTML string to disk, creating parent directories as needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
