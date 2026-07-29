# Devin Superset Remediation

Event-driven automation that uses the [Devin API](https://docs.devin.ai/api-reference/overview)
to remediate issues filed against [mattyiceg-org/superset](https://github.com/mattyiceg-org/superset)
(a fork of Apache Superset).

**Status:** bootstrap stage. This currently serves a placeholder dashboard page
to prove the run/config/Docker path works end to end. The scan → dispatch →
poll → merge-check loop described in `PLAN.md` is not wired up yet.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DEVIN_API_KEY / GITHUB_TOKEN
uvicorn app.main:app --reload
```

Visit http://localhost:8000

## Run with Docker

```bash
cp .env.example .env   # fill in DEVIN_API_KEY / GITHUB_TOKEN
docker build -t devin-superset-remediation .
docker run --rm -p 8000:8000 --env-file .env devin-superset-remediation
```

## Configuration

- `config.yaml` — non-secret settings: which repo/label to watch, scan
  interval, max concurrent Devin sessions, playbook ID.
- `.env` (from `.env.example`) — secrets: `DEVIN_API_KEY`, `GITHUB_TOKEN`.
  Never committed.

## Next steps

See `../PLAN.md` for the full architecture: the scheduled scan loop, SQLite
state store, Devin session dispatch/poll, and the observability dashboard.
