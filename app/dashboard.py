from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.db import Database

STATUS_COLORS = {
    "queued": "#888888",
    "working": "#0969da",
    "pr_open": "#9a6700",
    "needs_review": "#cf222e",
    "merged": "#1a7f37",
    "closed": "#57606a",
}

NAV = """
<div style="margin-bottom:1.5rem; border-bottom:1px solid #d0d7de; padding-bottom:0.75rem;">
  <a href="/" style="margin-right:1.5rem; font-weight:600;">Inbox</a>
  <a href="/organization" style="font-weight:600;">Organization View</a>
</div>
"""

PAGE = """
<html>
  <head><title>{title}</title></head>
  <body style="font-family: sans-serif; max-width: 960px; margin: 3rem auto;">
    <h1>Devin Superset Remediation</h1>
    {nav}
    {body}
  </body>
</html>
"""


def _status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#888888")
    return (
        f'<span style="background:{color};color:white;padding:2px 8px;'
        f'border-radius:10px;font-size:0.85em;">{status}</span>'
    )


def _fmt_hours(hours) -> str:
    return f"{hours:.1f}h" if hours is not None else "—"


def _fmt_pct(numerator: int, denominator: int) -> str:
    return f"{(numerator / denominator * 100):.0f}%" if denominator else "—"


def _issue_table(rows, empty_message: str) -> str:
    if not rows:
        return f"<p style='color:#57606a;'>{empty_message}</p>"

    body_rows = "".join(
        f"""
        <tr>
          <td><a href="{r['issue_url']}">#{r['issue_number']}</a></td>
          <td>{r['issue_title']}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{f'<a href="{r["session_url"]}">session</a>' if r['session_url'] else '—'}</td>
          <td>{f'<a href="{r["pr_url"]}">PR</a>' if r['pr_url'] else '—'}</td>
        </tr>
        """
        for r in rows
    )
    return f"""
    <table border="1" cellpadding="8" cellspacing="0"
           style="border-collapse:collapse; width:100%; margin-bottom:2rem;">
      <tr><th>Issue</th><th>Title</th><th>Status</th><th>Devin Session</th><th>PR</th></tr>
      {body_rows}
    </table>
    """


def _tile(value, label: str) -> str:
    return (
        '<div style="text-align:center;">'
        f'<div style="font-size:2rem; font-weight:700;">{value}</div>'
        f'<div style="color:#57606a;">{label}</div>'
        "</div>"
    )


def _tile_row(*tiles: str) -> str:
    return f'<div style="display:flex; gap:2.5rem; margin:1.5rem 0;">{"".join(tiles)}</div>'


def build_router(store: Database, config: dict) -> APIRouter:
    """Owns all dashboard presentation. Takes store/config as plain
    constructor args rather than FastAPI's Depends() machinery — there's
    exactly one of each for this whole process, so DI would be ceremony
    without benefit here."""
    router = APIRouter()
    gh_cfg = config["github"]
    repo = f"{gh_cfg['owner']}/{gh_cfg['repo']}"
    max_concurrent = config["scan"]["max_concurrent_sessions"]

    @router.get("/", response_class=HTMLResponse)
    def inbox() -> str:
        active = store.get_in_flight()
        resolved = store.get_final()

        body = f"""
        <p>Watching <code>{repo}</code> for issues labeled <code>{gh_cfg['label']}</code>,
        scanning every {config['scan']['interval_minutes']} minute(s).</p>

        <h2>Needs Attention ({len(active)})</h2>
        {_issue_table(active, "Nothing in flight right now.")}

        <h2>Resolved ({len(resolved)})</h2>
        {_issue_table(resolved, "Nothing resolved yet.")}
        """
        return PAGE.format(title="Inbox — Devin Superset Remediation", nav=NAV, body=body)

    @router.get("/organization", response_class=HTMLResponse)
    def organization() -> str:
        m = store.get_org_metrics()
        triaged = m["triaged"] or 0
        success = (m["merged_count"] or 0) + (m["closed_after_response"] or 0)
        needs_review = m["needs_review_count"] or 0
        working = m["working_count"] or 0

        body = f"""
        <h2>Volume</h2>
        {_tile_row(
            _tile(m["total_issues"] or 0, "issues discovered"),
            _tile(triaged, "triaged by Devin"),
        )}

        <h2>Outcomes</h2>
        {_tile_row(
            _tile(success, "resolved successfully"),
            _tile(_fmt_pct(success, triaged), "success rate"),
            _tile(needs_review, "needed human review"),
            _tile(_fmt_pct(needs_review, triaged), "needs-review rate"),
        )}

        <h2>Speed</h2>
        {_tile_row(
            _tile(_fmt_hours(m["avg_hours_issue_to_pr"]), "avg issue → PR"),
            _tile(_fmt_hours(m["avg_hours_pr_to_merge"]), "avg PR → merge"),
        )}

        <h2>Capacity</h2>
        {_tile_row(_tile(f"{working}/{max_concurrent}", "concurrent sessions in use"))}
        """
        return PAGE.format(
            title="Organization View — Devin Superset Remediation", nav=NAV, body=body
        )

    @router.get("/api/status")
    def api_status() -> dict:
        return {
            "active": [dict(r) for r in store.get_in_flight()],
            "resolved": [dict(r) for r in store.get_final()],
        }

    @router.get("/api/org-metrics")
    def api_org_metrics() -> dict:
        return store.get_org_metrics()

    return router
