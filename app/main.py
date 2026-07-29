import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

load_dotenv()

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
config = yaml.safe_load(CONFIG_PATH.read_text())

app = FastAPI(title="Devin Superset Remediation")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    repo = f"{config['github']['owner']}/{config['github']['repo']}"
    label = config["github"]["label"]
    has_devin_key = bool(os.environ.get("DEVIN_API_KEY"))
    has_github_token = bool(os.environ.get("GITHUB_TOKEN"))

    return f"""
    <html>
      <head><title>Devin Superset Remediation</title></head>
      <body style="font-family: sans-serif; max-width: 640px; margin: 4rem auto;">
        <h1>Devin Superset Remediation</h1>
        <p>Hello world — this is a placeholder dashboard. The real version will
        show per-issue remediation status, PR links, and rollup metrics here.</p>
        <ul>
          <li>Watching: <code>{repo}</code> (label: <code>{label}</code>)</li>
          <li>DEVIN_API_KEY loaded: {has_devin_key}</li>
          <li>GITHUB_TOKEN loaded: {has_github_token}</li>
        </ul>
      </body>
    </html>
    """


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
