"""
komdigi_client.py — Universal Captcha Solver Client SDK.

Dapat digunakan oleh bot atau aplikasi apa pun di dalam jaringan Tailscale
(seperti polymarket_bot, clinic-bridge, web scraper, script otomatisasi)
untuk mendelegasikan penyelesaian captcha ke komdigi-bot service 24/7 di VPS Singapore.

Contoh Penggunaan:
    from komdigi_client import KomdigiCaptchaClient

    solver = KomdigiCaptchaClient()
    result = solver.solve("https://democaptcha.com/demo-form-eng/image.html")
    if result.get("status") == "pass":
        print("Captcha berhasil dipecahkan!", result)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional
import httpx

logger = logging.getLogger("komdigi_client")

DEFAULT_SERVICE_URL = os.getenv("KOMDIGI_SERVICE_URL", "http://127.0.0.1:8080")


class KomdigiCaptchaClient:
    """Client SDK untuk memanggil service solver captcha komdigi-bot."""

    def __init__(self, service_url: str = DEFAULT_SERVICE_URL, timeout: float = 90.0) -> None:
        self.service_url = service_url.rstrip("/")
        self.timeout = timeout

    def check_health(self) -> dict[str, Any]:
        """Periksa apakah service komdigi-bot aktif dan sehat."""
        url = f"{self.service_url}/health"
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()

    def submit(self, target_url: str) -> str:
        """Kirim target URL ke antrean captcha. Mengembalikan job_id."""
        url = f"{self.service_url}/solve"
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json={"url": target_url})
            resp.raise_for_status()
            data = resp.json()
            return data["job_id"]

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Cek status dan hasil pengerjaan job."""
        url = f"{self.service_url}/job/{job_id}"
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()

    def solve(
        self,
        target_url: str,
        poll_interval: float = 2.0,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        Kirim target URL dan tunggu hingga captcha selesai dipecahkan (blocking).

        Returns dict:
            {"status": "pass" | "fail", "family": str, "engine": str, ...}
        """
        max_timeout = timeout or self.timeout
        start = time.time()

        job_id = self.submit(target_url)
        logger.info("Job submitted: %s for %s", job_id, target_url)

        while time.time() - start < max_timeout:
            time.sleep(poll_interval)
            job = self.get_job(job_id)
            status = job.get("status")

            if status == "done":
                res = job.get("result") or {}
                logger.info("Job %s completed: %s", job_id, res.get("status"))
                return res
            elif status == "failed":
                logger.error("Job %s failed: %s", job_id, job.get("error"))
                return {"status": "fail", "error": job.get("error")}

        raise TimeoutError(f"Captcha solving timed out after {max_timeout}s (Job ID: {job_id})")


# Shortcut helper function
def solve_captcha(target_url: str, service_url: str = DEFAULT_SERVICE_URL) -> dict[str, Any]:
    """Helper fungsi instan satu baris untuk memecahkan captcha."""
    client = KomdigiCaptchaClient(service_url=service_url)
    return client.solve(target_url)
