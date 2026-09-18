"""Tests for GitHubClient."""
from __future__ import annotations

import io
import json
import os
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from hermetic.client.github import GitHubClient, GitHubClientError, GitHubIssue


live = pytest.mark.skipif(
    not os.getenv("HERMETIC_RUN_LIVE_TESTS") or not os.getenv("GITHUB_TOKEN"),
    reason="Set HERMETIC_RUN_LIVE_TESTS=1 and GITHUB_TOKEN to run live GitHub tests",
)


def _make_mock_response(status: int, data: dict | bytes) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    if isinstance(data, dict):
        raw_bytes = json.dumps(data).encode("utf-8")
    else:
        raw_bytes = data
    resp.read.return_value = raw_bytes
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None
    return resp


class TestGitHubClient:
    def test_fetch_issue_returns_github_issue_dataclass(self) -> None:
        payload = {
            "data": {
                "repository": {
                    "issue": {
                        "title": "Implement feature X",
                        "body": "Detailed description of feature X.",
                        "url": "https://github.com/octocat/Hello-World/issues/42",
                    }
                }
            }
        }
        client = GitHubClient(token="ghp_secret_token_123")
        with patch("urllib.request.urlopen", return_value=_make_mock_response(200, payload)):
            issue = client.fetch_issue("octocat", "Hello-World", 42)

        assert isinstance(issue, GitHubIssue)
        assert issue.owner == "octocat"
        assert issue.repo == "Hello-World"
        assert issue.number == 42
        assert issue.title == "Implement feature X"
        assert issue.body == "Detailed description of feature X."
        assert issue.url == "https://github.com/octocat/Hello-World/issues/42"

    def test_fetch_issue_raises_on_http_error(self) -> None:
        client = GitHubClient(token="invalid_token")
        http_err = urllib.error.HTTPError(
            url="https://api.github.com/graphql",
            code=401,
            msg="Unauthorized",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"message": "Bad credentials"}'),
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(GitHubClientError) as exc_info:
                client.fetch_issue("octocat", "Hello-World", 42)

        assert exc_info.value.status_code == 401
        assert "401" in str(exc_info.value)
        # Token must never be in exception message
        assert "invalid_token" not in str(exc_info.value)

    def test_fetch_issue_raises_on_graphql_errors_field(self) -> None:
        payload = {
            "errors": [
                {"message": "Could not resolve to a Repository with the name 'octocat/BadRepo'."}
            ]
        }
        client = GitHubClient(token="ghp_token")
        with patch("urllib.request.urlopen", return_value=_make_mock_response(200, payload)):
            with pytest.raises(GitHubClientError) as exc_info:
                client.fetch_issue("octocat", "BadRepo", 42)

        assert "Could not resolve" in str(exc_info.value)

    def test_fetch_issue_raises_on_malformed_json(self) -> None:
        client = GitHubClient(token="ghp_token")
        with patch("urllib.request.urlopen", return_value=_make_mock_response(200, b"<html>502 Bad Gateway</html>")):
            with pytest.raises(GitHubClientError) as exc_info:
                client.fetch_issue("octocat", "Hello-World", 42)

        assert "Malformed JSON" in str(exc_info.value)

    def test_github_client_sets_auth_header(self) -> None:
        payload = {
            "data": {
                "repository": {
                    "issue": {
                        "title": "Title",
                        "body": "Body",
                        "url": "https://github.com/octocat/Hello-World/issues/1",
                    }
                }
            }
        }
        client = GitHubClient(token="my-secret-token")
        with patch("urllib.request.urlopen", return_value=_make_mock_response(200, payload)) as mock_urlopen:
            client.fetch_issue("octocat", "Hello-World", 1)

            req = mock_urlopen.call_args[0][0]
            auth_header = req.get_header("Authorization")
            assert auth_header == "bearer my-secret-token"

    def test_fetch_issue_raises_when_issue_not_found(self) -> None:
        payload = {
            "data": {
                "repository": {
                    "issue": None
                }
            }
        }
        client = GitHubClient(token="ghp_token")
        with patch("urllib.request.urlopen", return_value=_make_mock_response(200, payload)):
            with pytest.raises(GitHubClientError) as exc_info:
                client.fetch_issue("octocat", "Hello-World", 999)

        assert "Issue #999 not found" in str(exc_info.value)

    def test_fetch_issue_raises_when_repo_not_found(self) -> None:
        payload = {
            "data": {
                "repository": None
            }
        }
        client = GitHubClient(token="ghp_token")
        with patch("urllib.request.urlopen", return_value=_make_mock_response(200, payload)):
            with pytest.raises(GitHubClientError) as exc_info:
                client.fetch_issue("octocat", "MissingRepo", 1)

        assert "Repository not found" in str(exc_info.value)

    @live
    def test_live_fetch_issue(self) -> None:
        token = os.environ["GITHUB_TOKEN"]
        owner = os.getenv("GITHUB_OWNER", "octocat")
        repo = os.getenv("GITHUB_REPO", "Hello-World")
        client = GitHubClient(token=token)
        issue = client.fetch_issue(owner, repo, 1)
        assert issue.number == 1
        assert len(issue.title) > 0
