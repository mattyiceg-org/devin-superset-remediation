from __future__ import annotations

import re

from app.api_client import ApiClient

GITHUB_API = "https://api.github.com"

_PR_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    match = _PR_URL_RE.search(pr_url)
    if not match:
        raise ValueError(f"could not parse a PR reference from url: {pr_url}")
    owner, repo, number = match.groups()
    return owner, repo, int(number)


class GitHubClient(ApiClient):
    def __init__(self, token: str):
        super().__init__(
            GITHUB_API,
            token,
            extra_headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def list_labeled_issues(self, owner: str, repo: str, label: str) -> list[dict]:
        """Open issues on owner/repo carrying `label`, as plain dicts with
        keys: number, title, body, html_url, created_at. Single page (100
        max) — this project's issue volume never approaches that; pagination
        would be needed before reusing this against a busier repo."""
        data = self.get(
            f"/repos/{owner}/{repo}/issues",
            params={"labels": label, "state": "open", "per_page": 100},
        )
        return [
            {
                "number": item["number"],
                "title": item["title"],
                "body": item.get("body") or "",
                "html_url": item["html_url"],
                "created_at": item["created_at"],
            }
            for item in data
            if "pull_request" not in item  # the issues endpoint also returns PRs
        ]

    def comment_on_issue(self, owner: str, repo: str, issue_number: int, body: str) -> None:
        self.post(f"/repos/{owner}/{repo}/issues/{issue_number}/comments", json={"body": body})

    def is_issue_open(self, owner: str, repo: str, issue_number: int) -> bool:
        data = self.get(f"/repos/{owner}/{repo}/issues/{issue_number}")
        return data.get("state") == "open"

    def get_pr_merge_status(self, owner: str, repo: str, pr_number: int) -> tuple[bool, str | None]:
        """Returns (merged, merged_at). merged_at is None until GitHub reports a merge."""
        data = self.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        return bool(data.get("merged")), data.get("merged_at")
