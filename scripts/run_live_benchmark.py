"""
scripts/run_live_benchmark.py — Evaluasi live solver pada 4 skenario tantangan nyata.

Target Pengujian:
1. https://democaptcha.com/demo-form-eng/image.html (Image OCR)
2. https://2captcha.com/demo/text (Text Reasoning)
3. http://democaptcha.com/demo-form-eng/math-image.html (Math CAPTCHA)
4. https://2captcha.com/demo/normal (Normal Image CAPTCHA)

Usage:
    uv run python scripts/run_live_benchmark.py
"""

from __future__ import annotations

import time

from komdigi_bot.orchestrator import Orchestrator

TARGETS = [
    ("https://democaptcha.com/demo-form-eng/image.html", "democaptcha_image"),
    ("https://2captcha.com/demo/text", "2captcha_text"),
    ("https://democaptcha.com/demo-form-eng/math-image.html", "democaptcha_math"),
    ("https://2captcha.com/demo/normal", "2captcha_normal"),
]


def run_benchmark() -> None:
    print("=" * 60)
    print("KOMDIGI BOT — LIVE SOLVER BENCHMARK (4 SCENARIOS)")
    print("=" * 60)

    orch = Orchestrator(headless=True)
    results = []

    for url, label in TARGETS:
        print(f"\n--- Testing [{label}]: {url} ---")
        t0 = time.monotonic()
        try:
            res = orch.run(url)
            lat = time.monotonic() - t0
            status_val = (
                res.final_status.value
                if hasattr(res.final_status, "value")
                else str(res.final_status)
            )
            print(
                f"Result [{label}]: Status={status_val} | Family={res.family} | Engine={res.engine} | Latency={lat:.2f}s"
            )
            results.append((label, url, status_val, res.family, res.engine, lat))
        except Exception as exc:
            lat = time.monotonic() - t0
            print(f"Error [{label}]: {exc}")
            results.append((label, url, "ERROR", "unknown", "unknown", lat))

    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)
    for label, url, status, fam, eng, lat in results:
        mark = "PASS" if status.lower() == "pass" else "FAIL"
        print(f"[{mark}] {label:18} | {fam:12} | {eng:15} | {lat:.2f}s")
    print("=" * 60)


if __name__ == "__main__":
    run_benchmark()
