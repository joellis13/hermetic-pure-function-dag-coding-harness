"""Research schemas: inputs/outputs for the Research compute node (Story 7 / Roadmap)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ResearchQuery(BaseModel):
    """A structured codebase lookup request emitted by the Research Node."""
    model_config = ConfigDict(frozen=True)

    query: str = Field(..., description="Natural-language description of what to find")
    purpose: str = Field(..., description="Why this information is needed for the plan")
    search_regex: str | None = Field(default=None, description="Optional regex to run via grep/ripgrep")
    read_files: list[str] = Field(
        default_factory=list,
        description="Repo-relative file paths to read in full",
    )


class ResearchResult(BaseModel):
    """The Data Plane's response to a ResearchQuery."""
    model_config = ConfigDict(frozen=True)

    query: str = Field(..., description="Echo of the original ResearchQuery.query")
    findings: str = Field(..., description="Assembled text of the retrieved content")
    token_count_estimate: int = Field(
        default=0,
        ge=0,
        description="Character-count / 4 approximation for budget enforcement",
    )
