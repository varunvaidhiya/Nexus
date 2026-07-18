"""Background worker: runs the context-engine jobs on an interval.

python -m nexus_api.worker          # loop every NEXUS_SYNC_INTERVAL_SECONDS
python -m nexus_api.worker --once   # single pass (backfills, tests, cron)
"""

import argparse
import asyncio

import structlog

from nexus_api.config import get_settings
from nexus_api.jobs import pipeline
from nexus_api.jobs.framework import run_job
from nexus_api.logging import configure_logging

logger = structlog.get_logger()

JOBS = [
    ("embed_messages", pipeline.embed_pending),
    ("summarize", pipeline.summarize_pending),
    ("embed_notes", pipeline.embed_notes),
    ("rebuild_profile", pipeline.rebuild_profile),
]


async def run_all() -> None:
    for name, job in JOBS:
        await run_job(name, job)


async def main(once: bool) -> None:
    settings = get_settings()
    configure_logging(settings)
    logger.info("worker starting", interval=settings.sync_interval_seconds, once=once)
    while True:
        await run_all()
        if once:
            return
        await asyncio.sleep(settings.sync_interval_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    asyncio.run(main(parser.parse_args().once))
