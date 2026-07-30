from __future__ import annotations

from typing import Optional

from app.api_client import ApiClient

DEVIN_API = "https://api.devin.ai/v3"

# v3 `status` enum: new, claimed, running, exit, error, suspended, resuming.
# "exit" = session ended (check structured_output/pull_requests for outcome),
# "error" = session failed, "suspended" = stalled and needs a human (inactivity,
# usage limit, etc. — see status_detail). Everything else is still in flight.
TERMINAL_STATUSES = {"exit", "error", "suspended"}

# `status` can stay "running" indefinitely while Devin is blocked on a human
# — e.g. it asked a clarifying question. Without checking status_detail too,
# a stuck session sits as "working" forever: never surfaced, never freeing
# its concurrency slot.
NEEDS_HUMAN_STATUS_DETAILS = {"waiting_for_user", "waiting_for_approval"}


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def needs_human(status: str, status_detail: Optional[str]) -> bool:
    """True once nothing further will happen without a person stepping in —
    either the session actually ended (is_terminal), or it's stalled waiting
    on a human while `status` itself never leaves "running"."""
    return is_terminal(status) or status_detail in NEEDS_HUMAN_STATUS_DETAILS


class DevinClient(ApiClient):
    def __init__(self, token: str, org_id: str):
        super().__init__(f"{DEVIN_API}/organizations/{org_id}", token)

    def create_session(
        self,
        prompt: str,
        playbook_id: str,
        repos: list[str],
        tags: list[str],
        structured_output_schema: Optional[dict] = None,
    ) -> dict:
        """Returns a dict with at least: session_id, url."""
        body = {"prompt": prompt, "playbook_id": playbook_id, "repos": repos, "tags": tags}
        if structured_output_schema is not None:
            body["structured_output_schema"] = structured_output_schema

        return self.post("/sessions", json=body)

    def get_session(self, session_id: str) -> dict:
        """Returns a dict with: session_id, status, status_detail,
        pull_request_url (flattened from pull_requests[0].pr_url, or None),
        structured_output."""
        data = self.get(f"/sessions/{session_id}")
        pull_requests = data.get("pull_requests") or []
        pr_url = pull_requests[0]["pr_url"] if pull_requests else None

        return {
            "session_id": data["session_id"],
            "status": data["status"],
            "status_detail": data.get("status_detail"),
            "pull_request_url": pr_url,
            "structured_output": data.get("structured_output"),
        }

    def terminate_session(self, session_id: str) -> None:
        """Stops a running session. Archived (not hard-deleted) so it's still
        visible in the Devin dashboard for reference after a human closes the
        underlying issue out-of-band."""
        self.delete(f"/sessions/{session_id}", params={"archive": "true"})
