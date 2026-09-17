"""
Context Assembler — builds IssueContext bundles within soft token budget caps.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hermetic.schemas.context import CodeSnippet, ExternalDoc, IssueContext

PLANNING_BUDGET: int = 150_000
IMPLEMENTATION_BUDGET: int = 750_000


def estimate_tokens(text: str) -> int:
    """Character-count approximation: len(text) // 4."""
    return len(text) // 4


@dataclass(frozen=True)
class TokenBudgetExceeded:
    """
    Soft budget warning — not an exception.
    Returned alongside the IssueContext when items were dropped.
    """

    budget: int
    used: int
    skipped_items: list[str]  # descriptive labels like "snippet:src/foo.py" or "doc:https://..."


class ContextAssembler:
    """
    Assembles an IssueContext from repository files and external documentation
    while enforcing a token budget cap.
    """

    def __init__(self, repo_root: Path, token_budget: int = PLANNING_BUDGET) -> None:
        self._repo_root = repo_root.resolve()
        self._token_budget = token_budget

    def read_file_snippet(self, repo_relative_path: str) -> CodeSnippet:
        """
        Read a repo-relative file and return a CodeSnippet.
        start_line=1, end_line=number of lines in file.
        Raises FileNotFoundError if path does not exist.
        """
        file_path = (self._repo_root / repo_relative_path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {repo_relative_path}")

        content = file_path.read_text(encoding="utf-8")
        line_count = max(1, len(content.splitlines()))
        return CodeSnippet(
            file_path=repo_relative_path,
            content=content,
            start_line=1,
            end_line=line_count,
        )

    def assemble(
        self,
        issue_id: str,
        title: str,
        description: str,
        file_paths: list[str],
        doc_urls_and_content: list[tuple[str, str, str | None]],
    ) -> tuple[IssueContext, TokenBudgetExceeded | None]:
        """
        Build an IssueContext within the token budget.
        Missing files raise FileNotFoundError (not silently skipped).
        Oversized files are soft-skipped (added to TokenBudgetExceeded.skipped_items).
        """
        total_tokens = estimate_tokens(description)
        snippets: list[CodeSnippet] = []
        skipped: list[str] = []

        for file_path in file_paths:
            snippet = self.read_file_snippet(file_path)
            tokens = estimate_tokens(snippet.content)
            if total_tokens + tokens <= self._token_budget:
                snippets.append(snippet)
                total_tokens += tokens
            else:
                skipped.append(f"snippet:{file_path}")

        docs: list[ExternalDoc] = []
        for url, content, doc_title in doc_urls_and_content:
            tokens = estimate_tokens(content)
            if total_tokens + tokens <= self._token_budget:
                docs.append(ExternalDoc(url=url, content=content, title=doc_title))
                total_tokens += tokens
            else:
                skipped.append(f"doc:{url}")

        context = IssueContext(
            issue_id=issue_id,
            title=title,
            description=description,
            snippets=snippets,
            docs=docs,
        )
        warning = (
            TokenBudgetExceeded(
                budget=self._token_budget,
                used=total_tokens,
                skipped_items=skipped,
            )
            if skipped
            else None
        )
        return context, warning
