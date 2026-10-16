"""End-to-end (E2E) runner — live browser demo page verification.

Run as a module::

    uv run python -m komdigi_bot.e2e_runner
    uv run python -m komdigi_bot.e2e_runner --families text,image --headless

What it does:
1. Launches a real Chrome browser via Playwright.
2. Navigates to each target 2captcha demo page.
3. Runs ONE attempt per family.
4. Asserts the success marker is present on the page after solving.
5. Writes ``outputs/evidence/e2e-results.json`` with screenshots + status.
6. Exits 0 on all pass, 1 on any failure.

Prerequisites:
    - ``LLM_API_KEY`` and ``LLM_MODEL_VISION`` set in ``.env``
    - ``uv run playwright install chromium`` done at least once
    - OPTIONAL: ``TWOCAPTCHA_API_KEY`` for Turnstile/Arkose/GeeTest
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from komdigi_bot.benchmark import BENCHMARK_TARGETS
from komdigi_bot.orchestrator import Orchestrator
from komdigi_bot.solvers.base import SolveStatus

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("komdigi_bot.e2e_runner")

_RESULTS_PATH = Path("outputs/evidence/e2e-results.json")


def run_e2e(families: list[str] | None = None, headless: bool = True) -> int:
    """Run E2E tests. Returns exit code (0 = all pass, 1 = any fail)."""
    targets = BENCHMARK_TARGETS
    if families:
        targets = [t for t in targets if t["family"] in families]

    orch = Orchestrator(max_retries=2, headless=headless)
    results = []
    any_fail = False

    for target in targets:
        family = target["family"]
        url = target["url"]
        logger.info("E2E[%s]: running %s", family, url)
        t0 = time.monotonic()

        try:
            run = orch.run(url)
        except Exception as exc:  # noqa: BLE001
            logger.error("E2E[%s]: unhandled error: %s", family, exc)
            results.append(
                {
                    "family": family,
                    "url": url,
                    "status": "error",
                    "error": str(exc),
                    "latency_ms": round((time.monotonic() - t0) * 1000),
                }
            )
            any_fail = True
            continue

        status_str = run.final_status.value
        entry = {
            "family": family,
            "url": url,
            "status": status_str,
            "passed": run.passed,
            "latency_ms": round(run.total_latency_ms),
            "attempts": len(run.attempts),
            "engine": run.engine,
            "screenshots": [a.screenshot_path for a in run.attempts if a.screenshot_path],
        }
        results.append(entry)

        if run.final_status == SolveStatus.PASS:
            logger.info("E2E[%s]: ✅ PASS (%.0f ms)", family, run.total_latency_ms)
        elif run.final_status == SolveStatus.SKIP:
            logger.info("E2E[%s]: ⏭  SKIP (captcha not found or unsupported)", family)
        else:
            logger.error("E2E[%s]: ❌ FAIL after %d attempts", family, len(run.attempts))
            any_fail = True

    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    logger.info("E2E results written to %s", _RESULTS_PATH)

    # Print summary
    print(f"\n{'=' * 55}")
    print("  E2E RESULTS")
    print(f"  {'Family':<14} {'Status':>8} {'ms':>8} {'Attempts':>9}")
    print(f"  {'-' * 50}")
    for r in results:
        icon = "✅" if r.get("passed") else ("⏭" if r["status"] == "skip" else "❌")
        print(
            f"  {r['family']:<14} {icon} {r['status']:>6} {r.get('latency_ms', 0):>8}  {r.get('attempts', 0):>8}"
        )
    print(f"{'=' * 55}\n")

    return 1 if any_fail else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="KOMDIGI E2E captcha solver runner")
    parser.add_argument(
        "--families", default="", help="Comma-separated families to test (default all)"
    )
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    args = parser.parse_args()

    families = [f.strip() for f in args.families.split(",") if f.strip()] or None
    return run_e2e(families=families, headless=not args.no_headless)


if __name__ == "__main__":
    sys.exit(main())
