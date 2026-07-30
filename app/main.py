from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI

from app import dashboard, scheduler
from app.db import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
config = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text())
store = Database(config["storage"]["db_path"])


async def _background_loop() -> None:
    interval_seconds = config["scan"]["interval_minutes"] * 60
    while True:
        try:
            await asyncio.to_thread(scheduler.tick, config)
        except Exception:
            # A single bad tick (transient network blip, malformed API response,
            # etc.) shouldn't kill the loop for the rest of the process's life.
            logger.exception("background tick failed, will retry next interval")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # store's __init__ already ensured the schema exists (module load time).
    task = asyncio.create_task(_background_loop())
    logger.info(
        "started background scan loop, interval=%ss", config["scan"]["interval_minutes"] * 60
    )
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Devin Superset Remediation", lifespan=lifespan)
app.include_router(dashboard.build_router(store, config))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
