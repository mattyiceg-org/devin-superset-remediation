from __future__ import annotations

import json
import logging
import os
import sqlite3

import requests

from app.db import Database
from app.devin_client import DevinClient, needs_human
from app.github_client import GitHubClient, parse_pr_url

logger = logging.getLogger(__name__)

TRIAGE_COMMENT = (
    "🤖 Picked up for automated remediation. A Devin session will be dispatched "
    "shortly (subject to this project's concurrency limit) — this comment will "
    "be followed by a pull request once it's done."
)


def _build_prompt(row: sqlite3.Row) -> str:
    return (
        f"Resolve GitHub issue #{row['issue_number']} in this repository.\n\n"
        f"Title: {row['issue_title']}\n\n"
        f"Body:\n{row['issue_body']}\n\n"
        f"Issue URL: {row['issue_url']}"
    )


def _scan(config: dict, store: Database, github: GitHubClient) -> int:
    """Find newly-labeled issues, insert them as queued, and comment that
    they've been picked up. Returns the number newly discovered."""
    gh_cfg = config["github"]

    try:
        issues = github.list_labeled_issues(gh_cfg["owner"], gh_cfg["repo"], gh_cfg["label"])
    except requests.RequestException:
        logger.exception("scan: failed to list labeled issues, skipping this cycle")
        return 0

    discovered = 0
    for issue in issues:
        if store.issue_exists(issue["number"]):
            continue
        store.insert_queued(
            issue["number"], issue["title"], issue["body"], issue["html_url"], issue["created_at"]
        )
        discovered += 1
        logger.info("scan: discovered issue #%s: %s", issue["number"], issue["title"])
        try:
            github.comment_on_issue(
                gh_cfg["owner"], gh_cfg["repo"], issue["number"], TRIAGE_COMMENT
            )
        except requests.RequestException:
            # Non-fatal: the issue is still tracked and will be dispatched;
            # it just won't have the "triaging" comment.
            logger.exception("scan: failed to post triaging comment on #%s", issue["number"])
    return discovered


def _dispatch(config: dict, store: Database, github: GitHubClient, devin: DevinClient) -> int:
    """Create Devin sessions for queued issues, up to the concurrency cap.
    Returns the number dispatched."""
    gh_cfg = config["github"]
    devin_cfg = config["devin"]
    max_concurrent = config["scan"]["max_concurrent_sessions"]

    slots = max(0, max_concurrent - store.count_working())
    if slots == 0:
        return 0

    dispatched = 0
    for row in store.get_queued(limit=slots):
        try:
            result = devin.create_session(
                prompt=_build_prompt(row),
                playbook_id=devin_cfg["playbook_id"],
                repos=[f"{gh_cfg['owner']}/{gh_cfg['repo']}"],
                tags=["superset-remediation", f"issue-{row['issue_number']}"],
            )
        except requests.RequestException:
            # Left as "queued" — picked up again next tick rather than lost.
            logger.exception("dispatch: failed to create session for #%s", row["issue_number"])
            continue
        store.mark_dispatched(row["issue_number"], result["session_id"], result["url"])
        dispatched += 1
        logger.info(
            "dispatch: issue #%s -> session %s", row["issue_number"], result["session_id"]
        )
    return dispatched


def _poll(store: Database, devin: DevinClient) -> int:
    """Check in-flight sessions — working, needs_review, AND pr_open, since a
    session doesn't stop being alive on Devin's side just because we've
    flagged it needs_review, or stop iterating just because it already opened
    a PR. Returns the number that changed state this tick."""
    transitioned = 0
    for row in store.get_pollable():
        try:
            status = devin.get_session(row["session_id"])
        except requests.RequestException:
            logger.exception("poll: failed to fetch session for #%s", row["issue_number"])
            continue

        # Devin can open a PR well before the session reaches a terminal
        # state (e.g. it keeps iterating after opening it). Record it as
        # soon as it's seen so the dashboard doesn't wait on session
        # termination to show a PR that already exists.
        pr_url = status["pull_request_url"]
        if pr_url and not row["pr_url"]:
            # PR number isn't in the session response; the merge-check step
            # resolves it from the URL via parse_pr_url.
            store.set_pr_info(row["issue_number"], None, pr_url)
            logger.info(
                "poll: issue #%s has a PR while still %s: %s",
                row["issue_number"],
                status["status"],
                pr_url,
            )

        # Covers both real termination (exit/error/suspended) AND a session
        # stuck at status="running" with status_detail="waiting_for_user" —
        # Devin asked a question and nothing will happen without a person,
        # even though the top-level status never leaves "running".
        if not needs_human(status["status"], status["status_detail"]):
            continue

        structured_output = status["structured_output"]
        structured_output_json = json.dumps(structured_output) if structured_output else None

        if status["status"] == "exit" and pr_url:
            store.mark_finished_with_pr(row["issue_number"], structured_output_json)
            logger.info("poll: issue #%s finished with a PR", row["issue_number"])
        else:
            # "exit" with no PR, "error", "suspended", or stuck waiting on a
            # human all need a look — this is exactly that signal.
            store.mark_needs_review(row["issue_number"], structured_output_json)
            logger.info(
                "poll: issue #%s needs review (status=%s, status_detail=%s)",
                row["issue_number"],
                status["status"],
                status["status_detail"],
            )
        transitioned += 1
    return transitioned


def _check_merges(store: Database, github: GitHubClient) -> int:
    """Check open PRs for merge status. Returns the number newly merged."""
    merged = 0
    for row in store.get_open_prs():
        try:
            owner, repo, pr_number = parse_pr_url(row["pr_url"])
            is_merged, merged_at = github.get_pr_merge_status(owner, repo, pr_number)
        except (ValueError, requests.RequestException):
            # ValueError: parse_pr_url couldn't parse row["pr_url"].
            logger.exception("merge-check: failed to check PR for #%s", row["issue_number"])
            continue

        if is_merged and merged_at:
            store.mark_merged(row["issue_number"], merged_at)
            merged += 1
            logger.info("merge-check: issue #%s's PR merged", row["issue_number"])
    return merged


def _reconcile_closed(config: dict, store: Database, github: GitHubClient, devin: DevinClient) -> int:
    """Catch issues a human closed out-of-band — directly, without going
    through a merge we detected. Runs after _check_merges so a PR merge that
    auto-closed its issue is already claimed as 'merged' by then, not
    mistaken for a human abandoning it. Terminates any live Devin session so
    nothing keeps running (and consuming credits) on work nobody wants."""
    gh_cfg = config["github"]

    closed = 0
    for row in store.get_in_flight():
        try:
            still_open = github.is_issue_open(gh_cfg["owner"], gh_cfg["repo"], row["issue_number"])
        except requests.RequestException:
            logger.exception(
                "reconcile: failed to check issue state for #%s", row["issue_number"]
            )
            continue

        if still_open:
            continue

        if row["session_id"]:
            try:
                devin.terminate_session(row["session_id"])
            except requests.RequestException:
                # Still mark it closed even if termination failed — the
                # human's intent matters more than this cleanup call
                # succeeding; it'll just keep running on Devin's side.
                logger.exception(
                    "reconcile: failed to terminate session for #%s", row["issue_number"]
                )

        store.mark_closed(row["issue_number"])
        closed += 1
        logger.info(
            "reconcile: issue #%s closed by a human, session terminated", row["issue_number"]
        )
    return closed


def tick(config: dict) -> dict:
    """One full cycle: scan -> poll -> check merges -> reconcile closed issues
    -> dispatch. Poll/merge-check run before dispatch so a session finishing
    this tick frees its concurrency slot for a queued issue in the same
    cycle, instead of sitting queued for one extra interval. Reconcile runs
    after merge-check so a merge-triggered auto-close isn't mistaken for a
    human abandoning the issue. Each step is independently fault-tolerant —
    a failure in one doesn't block the others."""
    store = Database(config["storage"]["db_path"])
    github = GitHubClient(os.environ["GITHUB_TOKEN"])
    devin = DevinClient(os.environ["DEVIN_API_KEY"], config["devin"]["org_id"])

    result = {
        "discovered": _scan(config, store, github),
        "transitioned": _poll(store, devin),
        "merged": _check_merges(store, github),
        "closed": _reconcile_closed(config, store, github, devin),
        "dispatched": _dispatch(config, store, github, devin),
    }
    logger.info("tick complete: %s", result)
    return result
