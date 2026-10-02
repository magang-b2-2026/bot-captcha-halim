"""
komdigi_bot/service/worker.py
Background worker thread — polls SQLite queue and runs Orchestrator.
Includes:
- Screenshot cleanup (files > 7 hari)
- AI Studio quota tracking
- Structured logging ke outputs/service.log
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from komdigi_bot.orchestrator import Orchestrator
from komdigi_bot.service.queue import JobQueue

logger = logging.getLogger("komdigi_bot.worker")

EVIDENCE_DIR     = Path("outputs/evidence")
MAX_EVIDENCE_AGE = 7 * 86400   # 7 hari dalam detik
MAX_EVIDENCE_MB  = 500         # hard cap disk usage


class QuotaTracker:
    """Simple in-memory daily quota counter untuk AI Studio."""

    def __init__(self, daily_limit: int = 1500) -> None:
        self._limit   = daily_limit
        self._count   = 0
        self._day     = self._today()
        self._lock    = threading.Lock()

    @staticmethod
    def _today() -> str:
        import datetime
        return datetime.date.today().isoformat()

    def increment(self) -> None:
        with self._lock:
            today = self._today()
            if today != self._day:          # reset daily
                self._count = 0
                self._day   = today
            self._count += 1
            remaining = self._limit - self._count
            if remaining <= 200:
                logger.warning(
                    "AI Studio quota warning: %d/%d used, %d remaining",
                    self._count, self._limit, remaining,
                )

    @property
    def remaining(self) -> int:
        with self._lock:
            if self._today() != self._day:
                return self._limit
            return max(0, self._limit - self._count)

    @property
    def used(self) -> int:
        with self._lock:
            if self._today() != self._day:
                return 0
            return self._count


def cleanup_evidence(max_age: int = MAX_EVIDENCE_AGE, max_mb: int = MAX_EVIDENCE_MB) -> None:
    """Hapus screenshot lama — jaga disk usage."""
    if not EVIDENCE_DIR.exists():
        return
    now = time.time()
    deleted = 0
    total_bytes = 0

    files = sorted(EVIDENCE_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime)
    for f in files:
        stat = f.stat()
        total_bytes += stat.st_size
        age = now - stat.st_mtime
        too_old = age > max_age
        too_big = total_bytes > max_mb * 1024 * 1024
        if too_old or too_big:
            f.unlink(missing_ok=True)
            total_bytes -= stat.st_size
            deleted += 1

    if deleted:
        logger.info("Cleanup: deleted %d screenshots, disk now ~%d MB",
                    deleted, total_bytes // (1024 * 1024))


class Worker:
    """Single background worker thread — runs forever until stop() called."""

    def __init__(
        self,
        queue: JobQueue,
        poll_interval: float = 1.0,
        orchestrator_kwargs: dict | None = None,
    ) -> None:
        self._queue    = queue
        self._poll     = poll_interval
        self._orch_kw  = orchestrator_kwargs or {}
        self._stop_evt = threading.Event()
        self._thread   = threading.Thread(target=self._loop, daemon=True, name="komdigi-worker")
        self.quota     = QuotaTracker()
        self._jobs_done   = 0
        self._jobs_failed = 0
        self._last_cleanup = 0.0

    def start(self) -> None:
        logger.info("Worker starting...")
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        logger.info("Worker stopping...")
        self._stop_evt.set()
        self._thread.join(timeout=timeout)

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def stats(self) -> dict:
        return {
            "jobs_done": self._jobs_done,
            "jobs_failed": self._jobs_failed,
            "quota_used": self.quota.used,
            "quota_remaining": self.quota.remaining,
            "worker_alive": self.is_alive,
        }

    def _loop(self) -> None:
        logger.info("Worker loop started")
        while not self._stop_evt.is_set():
            # Cleanup setiap 1 jam
            if time.time() - self._last_cleanup > 3600:
                cleanup_evidence()
                self._queue.cleanup_old(max_age_days=7)
                self._last_cleanup = time.time()

            job = self._queue.pop_pending()
            if not job:
                self._stop_evt.wait(timeout=self._poll)
                continue

            logger.info("Worker: processing job %s url=%s", job.id[:8], job.url)
            try:
                orch = Orchestrator(headless=True, **self._orch_kw)
                run_result = orch.run(job.url)
                result = {
                    "family":  run_result.family,
                    "engine":  run_result.engine,
                    "status":  run_result.final_status.value if hasattr(run_result.final_status, "value") else str(run_result.final_status),
                    "latency_ms": getattr(run_result, "latency_ms", None),
                }
                self._queue.complete(job.id, result)
                self.quota.increment()
                self._jobs_done += 1
                logger.info("Worker: job %s DONE family=%s status=%s",
                            job.id[:8], result["family"], result["status"])
            except Exception as exc:
                self._jobs_failed += 1
                err = f"{type(exc).__name__}: {exc}"
                self._queue.fail(job.id, err)
                logger.error("Worker: job %s FAILED — %s", job.id[:8], err)
