from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests

GITHUB_API = "https://api.github.com"

_PR_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


class GitHubClientError(Exception):
    pass


@dataclass
class Issue:
    number: int
    title: str
    body: str
    html_url: str
    created_at: str


def _session() -> requests.Session:
    token = os.environ["GITHUB_TOKEN"]
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return session


def list_labeled_issues(owner: str, repo: str, label: str) -> list[Issue]:
    """Open issues on owner/repo carrying `label`. Single page (100 max) — this
    project's issue volume never approaches that; pagination would be needed
    before reusing this against a busier repo."""
    try:
        resp = _session().get(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues",
            params={"labels": label, "state": "open", "per_page": 100},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        # TODO: retry with backoff on 5xx/timeout. For now, surface the error
        # and let the caller's tick() skip this cycle rather than crash the
        # background loop entirely.
        raise GitHubClientError(f"failed to list issues: {exc}") from exc

    issues = []
    for item in resp.json():
        if "pull_request" in item:  # GitHub's issues endpoint also returns PRs
            continue
        issues.append(
            Issue(
                number=item["number"],
                title=item["title"],
                body=item.get("body") or "",
                html_url=item["html_url"],
                created_at=item["created_at"],
            )
        )
    return issues


def comment_on_issue(owner: str, repo: str, issue_number: int, body: str) -> None:
    try:
        resp = _session().post(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise GitHubClientError(
            f"failed to comment on issue #{issue_number}: {exc}"
        ) from exc


def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    match = _PR_URL_RE.search(pr_url)
    if not match:
        raise GitHubClientError(f"could not parse a PR reference from url: {pr_url}")
    owner, repo, number = match.groups()
    return owner, repo, int(number)


def get_pr_merge_status(owner: str, repo: str, pr_number: int) -> tuple[bool, str | None]:
    """Returns (merged, merged_at). merged_at is None until GitHub reports a merge."""
    try:
        resp = _session().get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}",
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise GitHubClientError(f"failed to fetch PR #{pr_number}: {exc}") from exc

    data = resp.json()
    return bool(data.get("merged")), data.get("merged_at")
