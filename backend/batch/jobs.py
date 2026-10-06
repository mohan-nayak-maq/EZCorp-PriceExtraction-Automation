"""In-memory batch job store and async runner, backed by local SQLite storage.

The in-memory dict (``_JOBS``) is still the source of truth for a running
process - it's what every request reads/writes. ``storage.py`` is a
write-through log of the same data: every create/progress/completion is
persisted, and on module import every previously persisted job is reloaded
into ``_JOBS``, so job history survives a server restart instead of
vanishing with the process.

Because running jobs live in this process's memory, the service must run as a
single process (one uvicorn worker, one Container Apps replica); a second
replica would not see jobs started on the first.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from .. import storage
from ..categories.base import CategoryPlugin
from ..config import get_websearch_settings
from ..engine import public_error, search, search_multi
from ..models import BatchJob, BatchRowResult, SearchQuery

log = logging.getLogger(__name__)

# Cost guard-rails (no login in the pilot): cap how many batch jobs can run at
# once, per browser and across the whole server.
MAX_ACTIVE_JOBS_PER_CLIENT = 2
MAX_ACTIVE_JOBS_TOTAL = 5


class JobLimitError(Exception):
    """Too many jobs are already running; the message is safe to show to the user."""


def _load_persisted_jobs() -> dict[str, BatchJob]:
    loaded: dict[str, BatchJob] = {}
    for job in storage.load_jobs():
        # Anything still queued/running was cut off by a restart - nothing will
        # ever finish it, so close it out instead of leaving the UI polling forever.
        if job.status in ("queued", "running"):
            job.status = "error"
            job.error = "Interrupted by a server restart before it finished."
            storage.save_job(job)
            log.warning("Job %s was interrupted by a restart; marked as error", job.id)
        loaded[job.id] = job
    return loaded


_JOBS: dict[str, BatchJob] = _load_persisted_jobs()
# Strong references to running job tasks: the event loop only keeps weak ones,
# so an unreferenced task can be garbage-collected mid-run.
_TASKS: set[asyncio.Task] = set()


def create_job(category: CategoryPlugin, rows: list[dict[str, str]], owner: str) -> BatchJob:
    active = [j for j in _JOBS.values() if j.status in ("queued", "running")]
    if sum(1 for j in active if j.owner == owner) >= MAX_ACTIVE_JOBS_PER_CLIENT:
        raise JobLimitError(
            f"You already have {MAX_ACTIVE_JOBS_PER_CLIENT} extractions running. "
            "Wait for one to finish, then try again."
        )
    if len(active) >= MAX_ACTIVE_JOBS_TOTAL:
        raise JobLimitError("The tool is busy with other extractions right now. Please try again in a few minutes.")

    job = BatchJob(
        id=uuid.uuid4().hex, category=category.key, total=len(rows), created_at=time.time(), owner=owner,
    )
    _JOBS[job.id] = job
    storage.save_job(job)
    log.info("Job %s created: category=%s, %d row(s)", job.id, category.key, len(rows))
    task = asyncio.create_task(_run_job(job.id, category, rows))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return job


def get_job(job_id: str, owner: str) -> BatchJob | None:
    """The job, or None if it doesn't exist or belongs to a different client."""
    job = _JOBS.get(job_id)
    if job is None or job.owner != owner:
        return None
    return job


def list_jobs(owner: str) -> list[BatchJob]:
    owned = (j for j in _JOBS.values() if j.owner == owner)
    return sorted(owned, key=lambda j: j.created_at, reverse=True)


async def _process_row(job_id: str, category: CategoryPlugin, index: int, row: dict[str, str]) -> BatchRowResult:
    default_country = category.allowed_countries[0] if category.allowed_countries else ""
    country = row.get("country") or default_country

    country_error = category.validate_country(country) if country else f"Missing country for row {index + 1}"
    field_errors = category.validate_fields(row)
    if not category.is_multi_site and not row.get("target_website", ""):
        field_errors.append("Missing target website")

    if country_error or field_errors:
        error = "; ".join([e for e in [country_error, *field_errors] if e])
        log.warning("Job %s row %d: validation failed - %s", job_id, index, error)
        return BatchRowResult(row_index=index, input_fields=row, error=error)

    label = category.subject_label(row)
    started = time.perf_counter()
    log.info("Job %s row %d: starting search for %r (country=%s)", job_id, index, label, country)
    try:
        if category.is_multi_site:
            result = await search_multi(country, row, category)
        else:
            query = SearchQuery(category=category.key, country=country, target_website=row["target_website"], fields=row)
            result = await search(query, category)
    except Exception as exc:  # keep one bad row from ever aborting the batch
        log.exception("Job %s row %d: failed with an unhandled exception", job_id, index)
        return BatchRowResult(row_index=index, input_fields=row, error=public_error(exc))
    elapsed = round(time.perf_counter() - started, 2)
    log.info("Job %s row %d: %s (%.2fs) - %r", job_id, index, result.status, elapsed, label)
    return BatchRowResult(row_index=index, input_fields=row, result=result, error=result.error)


async def _run_job(job_id: str, category: CategoryPlugin, rows: list[dict[str, str]]) -> None:
    job = _JOBS[job_id]
    job.status = "running"
    job.rows = [BatchRowResult(row_index=i, input_fields=row) for i, row in enumerate(rows)]
    storage.save_job(job)
    settings = get_websearch_settings()
    semaphore = asyncio.Semaphore(max(1, settings.websearch_batch_concurrency))
    log.info("Job %s: running %d row(s) at concurrency %d", job_id, job.total, settings.websearch_batch_concurrency)

    async def worker(index: int, row: dict[str, str]) -> None:
        async with semaphore:
            job.rows[index] = await _process_row(job_id, category, index, row)
            job.processed += 1
            storage.save_job(job)

    started = time.perf_counter()
    try:
        await asyncio.gather(*(worker(i, row) for i, row in enumerate(rows)))
        job.status = "done"
        matched = sum(1 for r in job.rows if r.result and r.result.status == "found")
        log.info(
            "Job %s: done in %.2fs - %d/%d matched",
            job_id, round(time.perf_counter() - started, 2), matched, job.total,
        )
    except Exception as exc:  # unexpected failure in the orchestration itself
        log.exception("Job %s: failed", job_id)
        job.status = "error"
        job.error = public_error(exc)
    finally:
        storage.save_job(job)
