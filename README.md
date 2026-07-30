# Devin Superset Remediation

Event-driven automation, built on the [Devin API](https://docs.devin.ai/api-reference/overview),
that remediates issues on [`mattyiceg-org/superset`](https://github.com/mattyiceg-org/superset)
(a fork of Apache Superset) and reports on the results through a small
dashboard.

## Prerequisites

- Docker
- A Devin API key (service-user, org-scoped)
- A GitHub personal access token with `repo` scope

## Setup

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `DEVIN_API_KEY` | Devin service-user API key |
| `GITHUB_TOKEN` | GitHub personal access token (`repo` scope) |

## Configuration

Non-secret settings live in `config.yaml`:

| Key | Purpose |
|---|---|
| `github.owner` / `github.repo` / `github.label` | Repository and issue label to watch |
| `scan.interval_minutes` | How often the scheduler runs |
| `scan.max_concurrent_sessions` | Cap on simultaneously active Devin sessions |
| `devin.org_id` / `devin.playbook_id` | Devin org and playbook used to dispatch sessions |

## Run

```bash
docker build -t devin-superset-remediation .
docker run --rm -p 8000:8000 --env-file .env \
  -v "$(pwd)/data:/srv/data" \
  devin-superset-remediation
```

Then open **http://localhost:8000**. The `-v` mount persists the SQLite
state file across container restarts.

## Architecture

```
   config.yaml / .env
          │
          ▼
   ┌─────────────┐        GitHub API         ┌────────────┐
   │  Scheduler   │ ───────────────────────►  │   GitHub    │
   │  (tick loop) │ ◄───────────────────────  │  (issues)   │
   └──────┬───────┘        Devin API         └────────────┘
          │       ───────────────────────►    ┌────────────┐
          │       ◄───────────────────────    │   Devin     │
          ▼                                    └────────────┘
   ┌─────────────┐
   │   SQLite     │◄──── read by ────┐
   └─────────────┘                    │
                              ┌──────────────┐
                              │  Dashboard    │
                              └──────────────┘
```

The **scheduler** is a background loop that scans for labeled issues,
dispatches and polls Devin sessions, and reconciles state against GitHub
(merges, manual closes). The **dashboard** is a small read-only view over the
same data. Both — along with the SQLite store between them — are
intentionally basic, built to demonstrate the pipeline rather than serve as a
production design.

## Usage

1. Label an issue on the watched repository with `devin-fix`.
2. On the next scheduler cycle, the issue is picked up automatically: a
   Devin session is dispatched, and a "picked up for remediation" comment is
   posted on the issue.
3. Devin works the issue and opens a pull request, commenting back with a
   link once it's done.
4. Check the dashboard for live status, outcomes, and rollup metrics.
