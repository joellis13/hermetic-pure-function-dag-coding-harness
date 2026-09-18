"""GitHub GraphQL API client."""
from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.error
import urllib.request


@dataclass(frozen=True)
class GitHubIssue:
    """Represents a GitHub issue fetched from the API."""
    owner: str
    repo: str
    number: int
    title: str
    body: str  # Markdown body of the issue
    url: str


class GitHubClientError(Exception):
    """Raised when an error occurs while communicating with the GitHub API."""
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


_GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
_ISSUE_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) {
      title
      body
      url
    }
  }
}
""".strip()


class GitHubClient:
    """Synchronous GitHub client using urllib and GraphQL."""

    def __init__(self, token: str) -> None:
        self._token = token

    def fetch_issue(self, owner: str, repo: str, number: int) -> GitHubIssue:
        """Fetch a single issue from GitHub GraphQL API."""
        payload = {
            "query": _ISSUE_QUERY,
            "variables": {
                "owner": owner,
                "repo": repo,
                "number": number,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"bearer {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "hermetic-pure-function-dag-coding-harness",
        }
        req = urllib.request.Request(
            _GRAPHQL_ENDPOINT,
            data=data,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                resp_bytes = resp.read()
        except urllib.error.HTTPError as exc:
            raise GitHubClientError(
                f"GitHub API HTTP error: {exc.code} {exc.reason}",
                status_code=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubClientError(
                f"GitHub network error: {exc.reason}",
            ) from exc
        except Exception as exc:
            raise GitHubClientError(f"Unexpected error communicating with GitHub: {exc}") from exc

        try:
            body_text = resp_bytes.decode("utf-8")
            result = json.loads(body_text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubClientError(f"Malformed JSON in GitHub API response: {exc}") from exc

        if not isinstance(result, dict):
            raise GitHubClientError("Malformed response from GitHub API: expected JSON object")

        if "errors" in result and result["errors"]:
            errors = result["errors"]
            error_msgs = [e.get("message", str(e)) for e in errors if isinstance(e, dict)]
            msg = "; ".join(error_msgs) if error_msgs else str(errors)
            raise GitHubClientError(f"GitHub GraphQL error: {msg}")

        data_field = result.get("data")
        if not isinstance(data_field, dict):
            raise GitHubClientError("Missing 'data' field in GitHub response")

        repository = data_field.get("repository")
        if repository is None:
            raise GitHubClientError(f"Repository not found: {owner}/{repo}")

        issue_data = repository.get("issue")
        if issue_data is None:
            raise GitHubClientError(f"Issue #{number} not found in {owner}/{repo}")

        title = issue_data.get("title", "")
        body = issue_data.get("body") or ""
        url = issue_data.get("url", f"https://github.com/{owner}/{repo}/issues/{number}")

        return GitHubIssue(
            owner=owner,
            repo=repo,
            number=number,
            title=title,
            body=body,
            url=url,
        )
