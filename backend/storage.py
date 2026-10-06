"""SQLite-backed local storage so run history survives server restarts.

Everything the tool produces - batch jobs (with every row) and ad-hoc single
lookups - is written here as it happens, in addition to living in the
in-memory job store (``batch/jobs.py``) for the current process. On startup,
``batch/jobs.py`` reloads every persisted job from here, so the History screen
keeps showing past runs across sessions/restarts, not just the current one.
Every job/search row carries an ``owner`` (the browser's anonymous X-Client-Id),
so each user's history only shows their own runs.

Stored as one JSON blob per row (the full Pydantic model) rather than a
normalised schema - the shapes are nested and category-specific enough that a
blob is simpler and the query needs here are just "list recent, fetch by id".
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .config import get_websearch_settings
from .models import BatchJob, SearchResult

log = logging.getLogger(__name__)

DATA_DIR: Path = get_websearch_settings().data_dir
DB_PATH = DATA_DIR / "websearch.db"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            status TEXT NOT NULL,
            total INTEGER NOT NULL,
            processed INTEGER NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS searches (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            subject_label TEXT,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            payload TEXT NOT NULL
        );
        """
    )
    for table in ("jobs", "searches"):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "owner" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
    conn.commit()
    _conn = conn
    log.info("Local storage ready at %s", DB_PATH)
    return conn


def save_job(job: BatchJob) -> None:
    """Insert or update one batch job's persisted state (called on every progress change)."""
    with _lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT INTO jobs (id, category, status, total, processed, created_at, updated_at, payload, owner)
            VALUES (:id, :category, :status, :total, :processed, :created_at, :updated_at, :payload, :owner)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                total = excluded.total,
                processed = excluded.processed,
                updated_at = excluded.updated_at,
                payload = excluded.payload,
                owner = excluded.owner
            """,
            {
                "id": job.id,
                "category": job.category,
                "status": job.status,
                "total": job.total,
                "processed": job.processed,
                "created_at": job.created_at,
                "updated_at": time.time(),
                "payload": job.model_dump_json(),
                "owner": job.owner,
            },
        )
        conn.commit()
    log.debug("Job %s persisted (status=%s, processed=%d/%d)", job.id, job.status, job.processed, job.total)


def load_jobs() -> list[BatchJob]:
    """Every persisted job, newest first - used to hydrate the in-memory store on startup."""
    with _lock:
        conn = _get_conn()
        rows = conn.execute("SELECT payload FROM jobs ORDER BY created_at DESC").fetchall()
    jobs = [BatchJob.model_validate_json(row[0]) for row in rows]
    log.info("Loaded %d job(s) from local storage", len(jobs))
    return jobs


def save_search(result: SearchResult, owner: str = "") -> None:
    """Record one ad-hoc (non-batch) lookup, e.g. from /api/search or the CLI."""
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO searches (id, category, subject_label, status, created_at, payload, owner) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                result.query.category,
                result.subject_label,
                result.status,
                time.time(),
                result.model_dump_json(),
                owner,
            ),
        )
        conn.commit()
    log.debug("Ad-hoc search persisted (%s, status=%s)", result.subject_label, result.status)


def load_searches(owner: str, limit: int = 200) -> list[SearchResult]:
    """Most recent ad-hoc lookups made by ``owner``, newest first."""
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT payload FROM searches WHERE owner = ? ORDER BY created_at DESC LIMIT ?", (owner, limit)
        ).fetchall()
    return [SearchResult.model_validate_json(row[0]) for row in rows]
