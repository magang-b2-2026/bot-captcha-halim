"""
komdigi_bot/service/chrome_cdp_solver.py
Chrome CDP solver untuk Turnstile & GeeTest — menggunakan Chrome asli
via remote debugging protocol sehingga fingerprint 100% legitimate.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from komdigi_bot.solvers.base import BaseSolver, SolveAttempt, SolveStatus, CAPTCHA_PASS_MARKER

logger = logging.getLogger("komdigi_bot.chrome_cdp")

CHROME_EXE  = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TEMP_PROFILE = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "KomdigiBotCDP")
CDP_PORT     = 9224   # port khusus untuk bot (beda dari Edge 9222)

SUPPORTED_FAMILIES = {"turnstile", "geetest", "arkose"}


class ChromeCDPSolver(BaseSolver):
    """
    Solve Turnstile / GeeTest / Arkose menggunakan Chrome asli via CDP.
    Chrome dengan temp profile + legitimate fingerprint → auto-pass.
    """
    ENGINE_KEY = "chrome_cdp"

    def __init__(self, url: str) -> None:
        self._url = url

    def solve(self, page, evidence_dir: Path) -> SolveAttempt:
        """
        page: Playwright page (Chromium stealth) — tidak dipakai di CDP mode,
        tapi kita butuh evidence_dir untuk screenshot.
        """
        import time as _time
        t0 = _time.monotonic()

        chrome_proc = None
        try:
            chrome_proc = self._launch_chrome()
            if not self._wait_cdp():
                return SolveAttempt(
                    family="turnstile", engine=self.ENGINE_KEY,
                    status=SolveStatus.FAIL,
                    message="Chrome CDP tidak ready setelah 30s",
                    latency_ms=(_time.monotonic() - t0) * 1000,
                )

            result = self._run_with_cdp(evidence_dir)
            return SolveAttempt(
                family=result["family"],
                engine=self.ENGINE_KEY,
                status=SolveStatus.PASS if result["passed"] else SolveStatus.FAIL,
                message=CAPTCHA_PASS_MARKER if result["passed"] else "Chrome CDP: success marker not found",
                screenshot_path=result.get("screenshot", ""),
                latency_ms=(_time.monotonic() - t0) * 1000,
            )
        except Exception as exc:
            logger.error("ChromeCDP: error: %s", exc)
            return SolveAttempt(
                family="turnstile", engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"Chrome CDP error: {exc}",
                latency_ms=(_time.monotonic() - t0) * 1000,
            )
        finally:
            if chrome_proc:
                chrome_proc.terminate()

    def _launch_chrome(self) -> subprocess.Popen:
        os.makedirs(TEMP_PROFILE, exist_ok=True)
        cmd = [
            CHROME_EXE,
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={TEMP_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-extensions",
            "about:blank",
        ]
        logger.info("ChromeCDP: launching Chrome on port %d", CDP_PORT)
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("ChromeCDP: Chrome PID=%d", proc.pid)
        return proc

    def _wait_cdp(self, timeout: int = 30) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2
                )
                logger.info("ChromeCDP: ready")
                return True
            except Exception:
                time.sleep(0.8)
        return False

    def _run_with_cdp(self, evidence_dir: Path) -> dict:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            ctx  = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            logger.info("ChromeCDP: navigating to %s", self._url)
            try:
                page.goto(self._url, wait_until="domcontentloaded", timeout=45_000)
            except Exception as exc:
                logger.warning("ChromeCDP: goto warning: %s", exc)

            time.sleep(5.0)  # tunggu challenge JS settle

            # Screenshot evidence
            shot = str(evidence_dir / "chrome_cdp_result.png")
            try:
                page.screenshot(path=shot)
            except Exception:
                shot = ""

            # Cek pass marker
            html = page.content()
            passed = CAPTCHA_PASS_MARKER.lower() in html.lower()

            if not passed:
                # Coba klik submit
                for sel in ["button[type='submit']", "#ts_submit",
                            "button:has-text('Check')", "button:has-text('Submit')"]:
                    try:
                        btn = page.query_selector(sel)
                        if btn and btn.is_visible():
                            btn.click()
                            time.sleep(4.0)
                            break
                    except Exception:
                        continue
                passed = CAPTCHA_PASS_MARKER.lower() in page.content().lower()

            logger.info("ChromeCDP: %s", "PASS" if passed else "FAIL")
            return {"passed": passed, "screenshot": shot, "family": "turnstile"}
