"""
komdigi_bot/service/api.py
FastAPI HTTP server untuk komdigi-bot service.

Endpoints:
  POST /solve           â€” submit captcha job
  GET  /job/{id}        â€” cek status job
  GET  /health          â€” health check (untuk monitoring)
  GET  /metrics         â€” statistik worker & queue
  DELETE /job/{id}      â€” cancel pending job
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl

from komdigi_bot.service.queue import JobQueue, JobStatus
from komdigi_bot.service.worker import Worker

logger = logging.getLogger("komdigi_bot.api")

# â”€â”€ Singleton state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_queue: JobQueue | None = None
_worker: Worker | None = None
_start_time = time.time()


# â”€â”€ Lifespan â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _queue, _worker
    logger.info("Starting komdigi-bot service...")

    _queue = JobQueue()
    _worker = Worker(_queue, poll_interval=1.0)
    _worker.start()
    logger.info("Worker started. Service ready.")

    yield  # â† server is running

    logger.info("Shutting down service...")
    if _worker:
        _worker.stop(timeout=15)
    logger.info("Service stopped.")


# â”€â”€ App â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
app = FastAPI(
    title="komdigi-bot Service",
    description="Captcha solving service â€” 6 captcha types supported",
    version="1.0.0",
    lifespan=lifespan,
)


# â”€â”€ Schemas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class SolveRequest(BaseModel):
    url: HttpUrl


class SolveResponse(BaseModel):
    job_id: str
    status: str
    message: str


# â”€â”€ Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.post("/solve", response_model=SolveResponse, status_code=202)
def submit_job(req: SolveRequest):
    """Submit URL untuk di-solve captchanya. Returns job_id untuk polling."""
    if _queue is None:
        raise HTTPException(503, "Service not ready")
    job = _queue.enqueue(str(req.url))
    logger.info("Job enqueued: %s -> %s", job.id[:8], req.url)
    return SolveResponse(
        job_id=job.id,
        status="pending",
        message="Job queued. Poll /job/{job_id} for result.",
    )


@app.get("/job/{job_id}")
def get_job(job_id: str):
    """Cek status dan hasil job."""
    if _queue is None:
        raise HTTPException(503, "Service not ready")
    job = _queue.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id!r} not found")
    return job.to_dict()


@app.delete("/job/{job_id}")
def cancel_job(job_id: str):
    """Cancel pending job (tidak bisa cancel yang sedang running)."""
    if _queue is None:
        raise HTTPException(503, "Service not ready")
    job = _queue.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id!r} not found")
    if job.status != JobStatus.PENDING:
        raise HTTPException(409, f"Job is {job.status.value}, cannot cancel")
    _queue.fail(job_id, "Cancelled by user")
    return {"message": "Job cancelled"}


@app.get("/health")
def health():
    """Health check endpoint â€” untuk monitoring / Windows Task Scheduler watchdog."""
    worker_alive = _worker.is_alive if _worker else False
    status = "ok" if worker_alive else "degraded"
    return JSONResponse(
        status_code=200 if worker_alive else 503,
        content={
            "status": status,
            "uptime_s": round(time.time() - _start_time),
            "worker_alive": worker_alive,
        },
    )


@app.get("/metrics")
def metrics():
    """Statistik operasional â€” quota, throughput, queue depth."""
    if _queue is None or _worker is None:
        raise HTTPException(503, "Service not ready")
    queue_stats = _queue.stats()
    worker_stats = _worker.stats
    return {
        "queue": queue_stats,
        "worker": worker_stats,
        "uptime_s": round(time.time() - _start_time),
        "quota": {
            "used_today": worker_stats["quota_used"],
            "remaining_today": worker_stats["quota_remaining"],
            "daily_limit": 1500,
        },
    }


@app.get("/")
def root():
    return {
        "service": "komdigi-bot",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }
