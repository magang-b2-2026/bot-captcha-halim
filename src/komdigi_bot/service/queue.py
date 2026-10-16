"""
komdigi_bot/service/queue.py
SQLite-backed job queue — persists across restarts.
Schema:
  jobs(id TEXT PK, url TEXT, status TEXT, created_at REAL,
       started_at REAL, finished_at REAL, result JSON, error TEXT)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

DB_PATH = Path("outputs/jobs.db")


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    url: str
    status: JobStatus
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class JobQueue:
    """Thread-safe SQLite job queue."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db, timeout=10, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._lock, self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id          TEXT PRIMARY KEY,
                    url         TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    created_at  REAL NOT NULL,
                    started_at  REAL,
                    finished_at REAL,
                    result      TEXT,
                    error       TEXT
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)")
            con.commit()

    def enqueue(self, url: str) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            url=url,
            status=JobStatus.PENDING,
            created_at=time.time(),
        )
        with self._lock, self._conn() as con:
            con.execute(
                "INSERT INTO jobs(id, url, status, created_at) VALUES (?,?,?,?)",
                (job.id, job.url, job.status.value, job.created_at),
            )
            con.commit()
        return job

    def pop_pending(self) -> Job | None:
        """Atomically claim one pending job → set to RUNNING."""
        with self._lock, self._conn() as con:
            row = con.execute(
                "SELECT * FROM jobs WHERE status='pending' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            now = time.time()
            con.execute(
                "UPDATE jobs SET status='running', started_at=? WHERE id=?",
                (now, row["id"]),
            )
            con.commit()
            return Job(
                id=row["id"],
                url=row["url"],
                status=JobStatus.RUNNING,
                created_at=row["created_at"],
                started_at=now,
            )

    def complete(self, job_id: str, result: dict) -> None:
        with self._lock, self._conn() as con:
            con.execute(
                "UPDATE jobs SET status='done', finished_at=?, result=? WHERE id=?",
                (time.time(), json.dumps(result), job_id),
            )
            con.commit()

    def fail(self, job_id: str, error: str) -> None:
        with self._lock, self._conn() as con:
            con.execute(
                "UPDATE jobs SET status='failed', finished_at=?, error=? WHERE id=?",
                (time.time(), error, job_id),
            )
            con.commit()

    def get(self, job_id: str) -> Job | None:
        with self._lock, self._conn() as con:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return None
            return Job(
                id=row["id"],
                url=row["url"],
                status=JobStatus(row["status"]),
                created_at=row["created_at"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                result=json.loads(row["result"]) if row["result"] else None,
                error=row["error"],
            )

    def stats(self) -> dict[str, int]:
        with self._lock, self._conn() as con:
            rows = con.execute("SELECT status, COUNT(*) as n FROM jobs GROUP BY status").fetchall()
            return {r["status"]: r["n"] for r in rows}

    def cleanup_old(self, max_age_days: int = 7) -> int:
        """Hapus job done/failed yang lebih lama dari max_age_days."""
        cutoff = time.time() - max_age_days * 86400
        with self._lock, self._conn() as con:
            cur = con.execute(
                "DELETE FROM jobs WHERE status IN ('done','failed') AND finished_at < ?",
                (cutoff,),
            )
            con.commit()
            return cur.rowcount
