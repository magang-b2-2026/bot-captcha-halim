import sys
import time

from komdigi_bot.orchestrator import Orchestrator

targets = [
    ("https://democaptcha.com/demo-form-eng/image.html", "democaptcha_image"),
    ("https://2captcha.com/demo/text", "2captcha_text"),
    ("http://democaptcha.com/demo-form-eng/math-image.html", "democaptcha_math"),
    ("https://2captcha.com/demo/normal", "2captcha_normal"),
]

print("=== STARTING LIVE SOLVER TEST ON 4 TARGETS ===")
orch = Orchestrator(headless=True)

results = []
for url, label in targets:
    print(f"\n--- Testing [{label}]: {url} ---")
    t0 = time.monotonic()
    try:
        res = orch.run(url)
        lat = time.monotonic() - t0
        status_val = res.final_status.value if hasattr(res.final_status, "value") else str(res.final_status)
        print(f"Result [{label}]: Status={status_val} | Family={res.family} | Engine={res.engine} | Duration={lat:.1f}s")
        results.append((label, url, status_val, res.family, res.engine, f"{lat:.1f}s"))
    except Exception as exc:
        print(f"Error [{label}]: {exc}")
        results.append((label, url, "ERROR", "unknown", "unknown", f"{time.monotonic()-t0:.1f}s"))

print("\n" + "="*60)
print("LIVE EVALUATION SUMMARY TABLE")
print("="*60)
for label, url, status, fam, eng, lat in results:
    mark = "PASS" if status.lower() == "pass" else "FAIL"
    print(f"[{mark}] {label:18} | {fam:10} | {eng:15} | {lat}")
