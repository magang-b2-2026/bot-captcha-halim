"""
komdigi_bot/service/chrome_cdp_solver.py — v1.1
Chrome CDP solver untuk Turnstile & GeeTest.

Fix v1.1: Jalankan chrome_cdp_runner.py sebagai subprocess terpisah agar
terisolasi dari asyncio event loop milik worker thread. Playwright sync API
tidak bisa dipanggil dari non-main thread — subprocess sepenuhnya menghindari
masalah ini karena memiliki event loop sendiri.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

from komdigi_bot.solvers.base import BaseSolver, SolveAttempt, SolveStatus, CAPTCHA_PASS_MARKER

logger = logging.getLogger("komdigi_bot.chrome_cdp")

# Path ke runner script (relatif terhadap project root)
_RUNNER = Path(__file__).parent.parent.parent.parent / "chrome_cdp_runner.py"

SUPPORTED_FAMILIES = {"turnstile", "geetest", "arkose"}


class ChromeCDPSolver(BaseSolver):
    """
    Solve Turnstile / GeeTest / Arkose menggunakan Chrome asli via CDP.

    v1.1 fix: runner dijalankan sebagai subprocess terpisah sehingga
    Playwright sync_playwright() dapat membuat asyncio event loop sendiri
    tanpa konflik dengan event loop worker thread.
    """
    ENGINE_KEY = "chrome_cdp"

    def __init__(self, url: str) -> None:
        self._url = url

    def solve(self, page, evidence_dir: Path) -> SolveAttempt:
        import time as _time
        t0 = _time.monotonic()
        family = "turnstile"

        try:
            result = self._run_subprocess(str(evidence_dir))
            passed  = result.get("passed", False)
            err_msg = result.get("error", "")

            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.PASS if passed else SolveStatus.FAIL,
                message=CAPTCHA_PASS_MARKER if passed else f"Chrome CDP: {err_msg or 'success marker not found'}",
                screenshot_path=result.get("screenshot", ""),
                latency_ms=(_time.monotonic() - t0) * 1000,
            )
        except Exception as exc:
            logger.error("ChromeCDP subprocess error: %s", exc)
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"Chrome CDP subprocess error: {exc}",
                latency_ms=(_time.monotonic() - t0) * 1000,
            )

    def _run_subprocess(self, evidence_dir: str) -> dict:
        """Spawn chrome_cdp_runner.py sebagai proses terpisah."""
        python_exe = sys.executable  # uv venv python
        runner     = str(_RUNNER.resolve())

        logger.info("ChromeCDP: spawning subprocess runner (url=%s)", self._url)
        proc = subprocess.run(
            [python_exe, runner, self._url, evidence_dir],
            capture_output=True,
            text=True,
            timeout=120,  # max 2 menit per captcha
        )

        # Log stderr (log dari runner)
        if proc.stderr.strip():
            for line in proc.stderr.strip().splitlines()[-5:]:
                logger.debug("cdp_runner: %s", line)

        if not proc.stdout.strip():
            raise RuntimeError(f"Runner returned no output (exit={proc.returncode})")

        result = json.loads(proc.stdout.strip())
        logger.info(
            "ChromeCDP: subprocess done — passed=%s exit=%d",
            result.get("passed"), proc.returncode,
        )
        return result
