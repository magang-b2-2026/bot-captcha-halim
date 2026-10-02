"""
real_browser_test.py — v4
Strategi: Launch Chrome asli dengan --remote-debugging-port=9222,
lalu Playwright connect via CDP. Ini memberikan:
- Fingerprint Chrome asli 100%
- Cookies nyata dari profil user
- TLS fingerprint Chrome (bukan Chromium)
"""
import sys, time, os, subprocess, logging
sys.path.insert(0, "src")

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("real_browser_test")

CHROME_EXE   = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE_DIR  = r"C:\Users\Naufal Halim\AppData\Local\Temp\ChromeCDPTest"  # temp profile — no lock conflict
PASS_MARKER  = "Captcha is passed successfully"
CDP_PORT     = 9223

TARGETS = [
    ("turnstile", "https://solvecaptcha.com/demo/cloudflare-turnstile"),
    ("geetest",   "https://solvecaptcha.com/demo/geetest"),
]


def launch_chrome_cdp() -> subprocess.Popen:
    """Launch Chrome asli dengan remote debugging port."""
    cmd = [
        CHROME_EXE,
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={PROFILE_DIR}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--disable-extensions",
        "--disable-sync",
        "about:blank",
    ]
    logger.info("Launching Chrome with CDP port %d...", CDP_PORT)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info("Chrome PID: %d — waiting for CDP ready...", proc.pid)
    return proc


def wait_for_cdp(timeout: int = 30) -> bool:
    """Tunggu sampai CDP endpoint ready."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2
            )
            data = resp.read().decode()
            logger.info("CDP ready: %s", data[:100])
            return True
        except Exception:
            time.sleep(0.8)
    logger.error("CDP endpoint tidak ready setelah %ds", timeout)
    return False



def test_url(page, family: str, url: str) -> dict:
    logger.info("[%s] -> %s", family, url)
    t0 = time.time()

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    except Exception as exc:
        logger.warning("[%s] goto: %s", family, exc)

    # Tunggu challenge JS settle
    time.sleep(5.0)

    os.makedirs("outputs/evidence", exist_ok=True)
    shot = f"outputs/evidence/real_{family}.png"
    try:
        page.screenshot(path=shot)
        logger.info("[%s] Screenshot: %s", family, shot)
    except Exception as e:
        logger.warning("[%s] Screenshot failed: %s", family, e)

    def is_passed():
        try:
            return PASS_MARKER.lower() in page.content().lower()
        except Exception:
            return False

    if is_passed():
        status = "PASS (auto)"
    else:
        # Coba klik tombol submit
        for sel in [
            "button[type='submit']", "#ts_submit",
            "button:has-text('Check')", "button:has-text('Submit')",
            "button:has-text('Verify')", "input[type='submit']",
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    logger.info("[%s] Clicking: %s", family, sel)
                    btn.click()
                    time.sleep(4.0)
                    break
            except Exception:
                continue

        status = "PASS" if is_passed() else "FAIL"

    lat = round(time.time() - t0, 1)
    logger.info("[%s] %s in %ss", family, status, lat)
    return {"family": family, "status": status, "latency_s": lat}


def main():
    os.makedirs("outputs/evidence", exist_ok=True)

    # Launch Chrome asli
    chrome_proc = launch_chrome_cdp()

    if not wait_for_cdp(timeout=20):
        logger.error("Tidak bisa connect ke Chrome CDP. Abort.")
        chrome_proc.terminate()
        return

    results = []
    try:
        with sync_playwright() as p:
            logger.info("Connecting Playwright to Chrome via CDP...")
            browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")

            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            logger.info("Connected! Chrome version: %s", browser.version)

            for family, url in TARGETS:
                results.append(test_url(page, family, url))
                time.sleep(2.0)

            # Jangan close browser — biarkan user lihat hasilnya
            logger.info("Test selesai. Browser tetap terbuka untuk inspeksi.")
            time.sleep(3.0)

    finally:
        chrome_proc.terminate()
        logger.info("Chrome process terminated.")

    print("\n" + "=" * 55)
    print("  REAL CHROME (CDP) TEST RESULTS")
    print("=" * 55)
    for r in results:
        mark = "PASS" if "PASS" in r["status"] else "FAIL"
        print(f"  [{mark}] {r['family']:12s}  {r['status']:20s}  {r['latency_s']}s")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
