"""GitHub client subpackage."""
from __future__ import annotations

from hermetic.client.github import GitHubClient, GitHubClientError, GitHubIssue

__all__ = [
    "GitHubClient",
    "GitHubClientError",
    "GitHubIssue",
]
