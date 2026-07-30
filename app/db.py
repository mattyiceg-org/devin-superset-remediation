from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

STATUS_QUEUED = "queued"
STATUS_WORKING = "working"
STATUS_PR_OPEN = "pr_open"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_MERGED = "merged"
STATUS_CLOSED = "closed"  # human closed the issue out-of-band, not via a merge we detected

FINAL_STATUSES = (STATUS_MERGED, STATUS_CLOSED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS remediations (
    issue_number     INTEGER PRIMARY KEY,
    issue_title      TEXT NOT NULL,
    issue_body       TEXT NOT NULL,
    issue_url        TEXT NOT NULL,
    issue_opened_at  TEXT NOT NULL,

    status           TEXT NOT NULL,

    session_id       TEXT,
    session_url      TEXT,
    dispatched_at    TEXT,

    pr_number        INTEGER,
    pr_url           TEXT,
    pr_opened_at     TEXT,

    merged_at        TEXT,

    structured_output_json  TEXT,
    created_at               TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """SQLite-backed state store for the remediation lifecycle:
    queued -> working -> pr_open -> merged (or needs_review / closed).

    Three primitives (_query, _execute, _update) hold all the
    connection/commit plumbing; every public method below is just one
    hand-written SQL statement passed to one of them, grouped by which
    scheduler.py step uses it."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._execute(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Always fetches everything — a cursor can't be fetched from once
        its connection is closed, so there's no way to hand back an open
        cursor for the caller to .fetchone() on. Methods that want a single
        row just index into the list themselves (see issue_exists, etc.)."""
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def _execute(self, sql: str, params: tuple = ()) -> None:
        with self._connect() as conn:
            conn.execute(sql, params)

    def _update(self, issue_number: int, **fields) -> None:
        """UPDATE ... SET col = ?, ... WHERE issue_number = ? for whatever
        columns are passed as kwargs — the common case among writes."""
        set_clause = ", ".join(f"{col} = ?" for col in fields)
        self._execute(
            f"UPDATE remediations SET {set_clause} WHERE issue_number = ?",
            (*fields.values(), issue_number),
        )

    # --- scan (discover + triage) ---

    def issue_exists(self, issue_number: int) -> bool:
        rows = self._query("SELECT 1 FROM remediations WHERE issue_number = ?", (issue_number,))
        return bool(rows)

    def insert_queued(
        self, issue_number: int, title: str, body: str, url: str, issue_opened_at: str
    ) -> None:
        self._execute(
            """
            INSERT INTO remediations
                (issue_number, issue_title, issue_body, issue_url, issue_opened_at,
                 status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (issue_number, title, body, url, issue_opened_at, STATUS_QUEUED, _now()),
        )

    # --- dispatch ---

    def get_queued(self, limit: int) -> list[sqlite3.Row]:
        """Oldest GitHub issue first — `issue_opened_at`, not our own
        `created_at` (when we happened to discover it), since GitHub's issues
        API returns newest-first and a single scan tick would otherwise
        dispatch newest-first."""
        return self._query(
            "SELECT * FROM remediations WHERE status = ? ORDER BY issue_opened_at ASC LIMIT ?",
            (STATUS_QUEUED, limit),
        )

    def count_working(self) -> int:
        rows = self._query(
            "SELECT COUNT(*) AS n FROM remediations WHERE status = ?", (STATUS_WORKING,)
        )
        return rows[0]["n"]

    def mark_dispatched(self, issue_number: int, session_id: str, session_url: str) -> None:
        self._update(
            issue_number,
            status=STATUS_WORKING,
            session_id=session_id,
            session_url=session_url,
            dispatched_at=_now(),
        )

    # --- poll ---

    def get_pollable(self) -> list[sqlite3.Row]:
        """Every row with a live-or-recently-live session worth re-checking —
        working, needs_review, AND pr_open. A session doesn't stop being
        alive on Devin's side just because we've flagged it needs_review, and
        it can keep iterating (e.g. answering its own follow-up question)
        after opening a PR."""
        return self._query(
            "SELECT * FROM remediations WHERE session_id IS NOT NULL AND status NOT IN (?, ?)",
            FINAL_STATUSES,
        )

    def set_pr_info(self, issue_number: int, pr_number: Optional[int], pr_url: str) -> None:
        """Record a PR as soon as it's observed — Devin can open a PR while a
        session is still `running`, well before the session reaches a
        terminal state. Does NOT change `status`; that only happens once the
        session finishes (see mark_finished_with_pr). `pr_opened_at` is only
        set the first time (COALESCE), so re-polling doesn't skew the
        issue->PR metric."""
        self._execute(
            """
            UPDATE remediations
            SET pr_number = ?, pr_url = ?, pr_opened_at = COALESCE(pr_opened_at, ?)
            WHERE issue_number = ?
            """,
            (pr_number, pr_url, _now(), issue_number),
        )

    def mark_finished_with_pr(
        self, issue_number: int, structured_output_json: Optional[str]
    ) -> None:
        """Transition to pr_open once the session is actually terminal.
        Assumes set_pr_info already recorded the PR (called first in poll)."""
        self._update(
            issue_number, status=STATUS_PR_OPEN, structured_output_json=structured_output_json
        )

    def mark_needs_review(self, issue_number: int, structured_output_json: Optional[str]) -> None:
        self._update(
            issue_number, status=STATUS_NEEDS_REVIEW, structured_output_json=structured_output_json
        )

    # --- merge-check ---

    def get_open_prs(self) -> list[sqlite3.Row]:
        """Any row with a PR that isn't merged yet — deliberately not
        restricted to status='pr_open', since a PR can exist while status is
        still 'working' (see set_pr_info)."""
        return self._query(
            "SELECT * FROM remediations WHERE pr_url IS NOT NULL AND status != ?",
            (STATUS_MERGED,),
        )

    def mark_merged(self, issue_number: int, merged_at: str) -> None:
        self._update(issue_number, status=STATUS_MERGED, merged_at=merged_at)

    # --- reconcile closed ---

    def get_in_flight(self) -> list[sqlite3.Row]:
        """Every row not yet in a final state — including still-queued issues
        that haven't been dispatched. Used both to reconcile against live
        GitHub issue state each tick, and as the inbox's "Needs Attention"
        table — needs_review rows sort first there, since they're the ones
        actually waiting on a person."""
        return self._query(
            """
            SELECT * FROM remediations WHERE status NOT IN (?, ?)
            ORDER BY CASE WHEN status = 'needs_review' THEN 0 ELSE 1 END, issue_number DESC
            """,
            FINAL_STATUSES,
        )

    def mark_closed(self, issue_number: int) -> None:
        self._update(issue_number, status=STATUS_CLOSED)

    # --- dashboard ---

    def get_final(self) -> list[sqlite3.Row]:
        """Terminal rows — merged or closed — for the inbox's "Resolved"
        table. Most recently resolved first."""
        return self._query(
            """
            SELECT * FROM remediations WHERE status IN (?, ?)
            ORDER BY COALESCE(merged_at, dispatched_at, created_at) DESC
            """,
            FINAL_STATUSES,
        )

    def get_org_metrics(self) -> dict:
        """Aggregate counts/timings for the Organization View. Rate
        calculations (success rate, needs-review rate, etc.) are derived
        from these in dashboard.py, not here — this just reports raw counts."""
        rows = self._query(
            """
            SELECT
                COUNT(*) AS total_issues,
                SUM(CASE WHEN session_id IS NOT NULL THEN 1 ELSE 0 END) AS triaged,
                SUM(CASE WHEN status = 'merged' THEN 1 ELSE 0 END) AS merged_count,
                SUM(CASE WHEN status = 'closed' AND session_id IS NOT NULL
                    THEN 1 ELSE 0 END) AS closed_after_response,
                SUM(CASE WHEN status = 'needs_review' THEN 1 ELSE 0 END) AS needs_review_count,
                SUM(CASE WHEN status = 'working' THEN 1 ELSE 0 END) AS working_count,
                AVG(CASE WHEN pr_opened_at IS NOT NULL
                    THEN (julianday(pr_opened_at) - julianday(issue_opened_at)) * 24
                    ELSE NULL END) AS avg_hours_issue_to_pr,
                AVG(CASE WHEN merged_at IS NOT NULL
                    THEN (julianday(merged_at) - julianday(pr_opened_at)) * 24
                    ELSE NULL END) AS avg_hours_pr_to_merge
            FROM remediations
            """
        )
        return dict(rows[0])
