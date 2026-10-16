"""
chrome_cdp_runner.py — Subprocess runner untuk Chrome CDP solver.
Dipanggil oleh ChromeCDPSolver via subprocess.run() agar terisolasi
dari asyncio event loop milik worker thread.

Usage (internal):
    python chrome_cdp_runner.py <url> <evidence_dir>

Output: JSON ke stdout
  {"passed": true, "screenshot": "path/to/shot.png", "family": "turnstile"}
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,  # log ke stderr, result ke stdout
)
logger = logging.getLogger("cdp_runner")


def _find_chrome_executable() -> str:
    env_path = os.environ.get("CHROME_PATH") or os.environ.get("CHROME_BIN")
    if env_path and os.path.exists(env_path):
        return env_path

    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    which_chrome = (
        shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium")
    )
    if which_chrome:
        return which_chrome

    return "chrome"


CHROME_EXE = _find_chrome_executable()
TEMP_PROFILE = os.path.join(tempfile.gettempdir(), "KomdigiBotCDP")
CDP_PORT = 9224
PASS_MARKER = "Captcha is passed successfully"


def launch_chrome() -> subprocess.Popen:
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
    logger.info("Launching Chrome on port %d...", CDP_PORT)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info("Chrome PID=%d", proc.pid)
    return proc


def wait_cdp(timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2)
            logger.info("Chrome CDP ready")
            return True
        except Exception:
            time.sleep(0.8)
    logger.error("CDP not ready after %ds", timeout)
    return False


def run_cdp(url: str, evidence_dir: str) -> dict:
    from playwright.sync_api import sync_playwright

    os.makedirs(evidence_dir, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        logger.info("Navigating to %s", url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as exc:
            logger.warning("goto warning: %s", exc)

        time.sleep(5.0)

        shot = os.path.join(evidence_dir, "chrome_cdp_result.png")
        try:
            page.screenshot(path=shot)
        except Exception:
            shot = ""

        html = page.content()
        passed = PASS_MARKER.lower() in html.lower()

        if not passed:
            for sel in [
                "button[type='submit']",
                "#ts_submit",
                "button:has-text('Check')",
                "button:has-text('Submit')",
                "button:has-text('Verify')",
            ]:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        time.sleep(4.0)
                        break
                except Exception:
                    continue
            passed = PASS_MARKER.lower() in page.content().lower()

        logger.info("Result: %s", "PASS" if passed else "FAIL")
        return {"passed": passed, "screenshot": shot, "family": "turnstile"}


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: chrome_cdp_runner.py <url> <evidence_dir>"}))
        sys.exit(1)

    url = sys.argv[1]
    evidence_dir = sys.argv[2]

    chrome = None
    try:
        chrome = launch_chrome()
        if not wait_cdp():
            print(json.dumps({"passed": False, "error": "CDP not ready"}))
            sys.exit(1)

        result = run_cdp(url, evidence_dir)
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}))
        sys.exit(1)
    finally:
        if chrome:
            chrome.terminate()


if __name__ == "__main__":
    main()
