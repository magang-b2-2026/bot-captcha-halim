"""Benchmark harness — measure solver accuracy per captcha family.

Run as a module::

    uv run python -m komdigi_bot.benchmark

What it does:
1. For each demo URL in BENCHMARK_TARGETS, run the orchestrator N times.
2. Collect pass/fail/latency per family.
3. Rank vision models on image/click/rotate tasks.
4. Write ``outputs/evidence/benchmark.json`` with full results.
5. Print a summary table.

This is the source of truth used to pin ``LLM_MODEL_VISION`` in ``.env``.

Usage:
    TWOCAPTCHA_API_KEY=... LLM_API_KEY=... uv run python -m komdigi_bot.benchmark
    uv run python -m komdigi_bot.benchmark --runs 5 --families text,image
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from komdigi_bot.orchestrator import Orchestrator, RunResult
from komdigi_bot.solvers.base import SolveStatus

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("komdigi_bot.benchmark")

_EVIDENCE_PATH = Path("outputs/evidence/benchmark.json")

# Target pages on 2captcha.com/demo — all public, no auth required
BENCHMARK_TARGETS: list[dict[str, str]] = [
    {"family": "text", "url": "https://2captcha.com/demo/text"},
    {"family": "image", "url": "https://2captcha.com/demo/normal"},
    {"family": "click", "url": "https://2captcha.com/demo/clickcaptcha"},
    {"family": "rotate", "url": "https://2captcha.com/demo/rotatecaptcha"},
    {"family": "recaptcha", "url": "https://2captcha.com/demo/recaptcha-v2"},
    {"family": "turnstile", "url": "https://2captcha.com/demo/cloudflare-turnstile"},
]

# Target pages on solvecaptcha.com/demo — user-specified test site
SOLVECAPTCHA_TARGETS: list[dict[str, str]] = [
    {"family": "image", "url": "https://solvecaptcha.com/demo/image-captcha"},
    {"family": "text", "url": "https://solvecaptcha.com/demo/text-captcha"},
    {"family": "recaptcha", "url": "https://solvecaptcha.com/demo/recaptcha-v2"},
    {"family": "turnstile", "url": "https://solvecaptcha.com/demo/cloudflare-turnstile"},
    {"family": "geetest", "url": "https://solvecaptcha.com/demo/geetest"},
]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@dataclass
class FamilyStats:
    family: str
    url: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    models_used: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0.0

    def record(self, result: RunResult) -> None:
        self.total += 1
        if result.final_status == SolveStatus.PASS:
            self.passed += 1
        elif result.final_status == SolveStatus.SKIP:
            self.skipped += 1
        else:
            self.failed += 1
        self.latencies_ms.append(result.total_latency_ms)
        for a in result.attempts:
            if a.llm_model:
                self.models_used.append(a.llm_model)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "url": self.url,
            "total_runs": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "pass_rate": round(self.pass_rate, 3),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "models_used": sorted(set(self.models_used)),
        }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_benchmark(
    runs_per_target: int = 3,
    families: list[str] | None = None,
    headless: bool = True,
    targets: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run the benchmark and return a results dict."""
    all_targets = targets if targets is not None else BENCHMARK_TARGETS
    if families:
        all_targets = [t for t in all_targets if t["family"] in families]

    orch = Orchestrator(max_retries=2, headless=headless)
    stats: dict[str, FamilyStats] = {
        t["family"]: FamilyStats(family=t["family"], url=t["url"]) for t in all_targets
    }

    total_runs = len(all_targets) * runs_per_target
    done = 0

    for target in all_targets:
        family = target["family"]
        url = target["url"]
        logger.info("Benchmark: starting %s (%d runs)", family, runs_per_target)

        for i in range(runs_per_target):
            logger.info("  Run %d/%d ...", i + 1, runs_per_target)
            try:
                result = orch.run(url)
                stats[family].record(result)
            except Exception as exc:  # noqa: BLE001
                logger.error("  Run error: %s", exc)
                dummy = RunResult(
                    run_id="error",
                    url=url,
                    family=family,
                    engine="unknown",
                    final_status=SolveStatus.FAIL,
                    error=str(exc),
                )
                stats[family].record(dummy)
            done += 1
            logger.info("  Progress: %d/%d total runs", done, total_runs)

    summary = {
        "benchmark_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runs_per_target": runs_per_target,
        "results": [s.to_dict() for s in stats.values()],
        "overall_pass_rate": round(
            sum(s.passed for s in stats.values()) / max(sum(s.total for s in stats.values()), 1),
            3,
        ),
    }
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    print(f"\n{'=' * 60}")
    print(f"  BENCHMARK RESULTS  — overall pass rate: {summary['overall_pass_rate']:.1%}")
    print(f"{'=' * 60}")
    print(f"  {'Family':<12} {'Pass':>5} {'Fail':>5} {'Skip':>5} {'Rate':>7} {'Avg ms':>8}")
    print(f"  {'-' * 55}")
    for r in summary["results"]:
        print(
            f"  {r['family']:<12} {r['passed']:>5} {r['failed']:>5} {r['skipped']:>5} "
            f"{r['pass_rate']:>7.1%} {r['avg_latency_ms']:>8.0f}"
        )
    print(f"{'=' * 60}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="KOMDIGI captcha solver benchmark")
    parser.add_argument("--runs", type=int, default=3, help="Runs per target (default 3)")
    parser.add_argument(
        "--families", default="", help="Comma-separated families to test (default all)"
    )
    parser.add_argument("--no-headless", action="store_true", help="Run with visible browser")
    parser.add_argument(
        "--site",
        choices=["2captcha", "solvecaptcha"],
        default="solvecaptcha",
        help="Demo site to benchmark against (default: solvecaptcha)",
    )
    args = parser.parse_args()

    families = [f.strip() for f in args.families.split(",") if f.strip()] or None

    # Select target set
    site_targets = SOLVECAPTCHA_TARGETS if args.site == "solvecaptcha" else BENCHMARK_TARGETS

    logger.info(
        "Starting benchmark: site=%s runs=%d families=%s",
        args.site,
        args.runs,
        families or "all",
    )
    summary = run_benchmark(
        runs_per_target=args.runs,
        families=families,
        headless=not args.no_headless,
        targets=site_targets,
    )

    _EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _EVIDENCE_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Results written to %s", _EVIDENCE_PATH)
    print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
