"""Context schemas: the read-only snapshot of an issue passed to AI compute nodes."""
from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CodeSnippet(BaseModel):
    """A slice of source code from a file, with optional line range."""
    model_config = ConfigDict(frozen=True)

    file_path: str = Field(..., description="Repo-relative path, e.g. 'src/hermetic/schemas/context.py'")
    content: str = Field(..., description="Verbatim source text of the snippet")
    start_line: int = Field(..., ge=1, description="1-indexed first line of the snippet")
    end_line: int = Field(..., ge=1, description="1-indexed last line of the snippet (inclusive)")

    @model_validator(mode="after")
    def _validate_line_range(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line ({self.end_line}) cannot be less than start_line ({self.start_line})"
            )
        return self

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


class ExternalDoc(BaseModel):
    """A piece of documentation fetched from an external URL."""
    model_config = ConfigDict(frozen=True)

    url: str = Field(..., description="Canonical URL of the document")
    content: str = Field(..., description="Markdown or plain-text body of the document")
    title: str | None = Field(default=None, description="Optional document title")


class IssueContext(BaseModel):
    """
    The complete hermetic context bundle passed to the Planning Node.

    Immutable once constructed. All fields are optional lists so that
    a minimal context (just a title + description) is always valid.
    """
    model_config = ConfigDict(frozen=True)

    issue_id: str = Field(..., description="Source-system ID, e.g. 'GH-42' or 'JIRA-100'")
    title: str = Field(..., description="Issue title / one-liner")
    description: str = Field(..., description="Full issue body in Markdown")
    snippets: list[CodeSnippet] = Field(default_factory=list)
    docs: list[ExternalDoc] = Field(default_factory=list)
