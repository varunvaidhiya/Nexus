"""Background-job plumbing: per-job advisory locks + job_run bookkeeping.

Jobs are idempotent coroutines taking a Session and returning a detail
string. Raise SkipJob when preconditions (e.g. no API key) aren't met —
that's a normal outcome, not an error.
"""

import zlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from nexus_api.db.models import JobRun, JobStatus
from nexus_api.db.session import get_engine

logger = structlog.get_logger()

Job = Callable[[Session], Awaitable[str]]


class SkipJob(Exception):
    """Preconditions not met; record the run as skipped."""


def _lock_key(name: str) -> int:
    return zlib.crc32(f"nexus-job:{name}".encode())


async def run_job(name: str, job: Job) -> JobStatus:
    """Run one job under an advisory lock, recording a job_run row."""
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        locked = session.execute(
            select(text("pg_try_advisory_lock(:key)")).params(key=_lock_key(name))
        ).scalar()
        if not locked:
            logger.info("job already running elsewhere", job=name)
            return JobStatus.skipped
        run = JobRun(name=name)
        session.add(run)
        session.commit()
        try:
            detail = await job(session)
            run.status, run.detail = JobStatus.success, detail
            logger.info("job finished", job=name, detail=detail)
        except SkipJob as skip:
            session.rollback()
            run.status, run.detail = JobStatus.skipped, str(skip)
            logger.info("job skipped", job=name, reason=str(skip))
        except Exception as exc:
            session.rollback()
            run.status, run.detail = JobStatus.error, f"{type(exc).__name__}: {exc}"[:500]
            logger.exception("job failed", job=name)
        finally:
            run.finished_at = datetime.now(UTC)
            session.add(run)
            session.commit()
            session.execute(select(text("pg_advisory_unlock(:key)")).params(key=_lock_key(name)))
        return run.status
