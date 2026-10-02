"""Captcha-solving orchestrator.

The orchestrator ties together the full pipeline:

1. Navigate to the target URL using :class:`~komdigi_bot.stealth.StealthBrowser`.
2. Run :class:`~komdigi_bot.triage.CaptchaRouter` to detect family + engine.
3. Dispatch the appropriate solver engine.
4. On failure, retry up to ``max_retries`` times (rotating profiles).
5. If in-house solvers exhaust retries AND ``solver_policy=hybrid``,
   escalate to :class:`~komdigi_bot.solvers.fallback.APIFallbackSolver`.
6. Return a :class:`RunResult` with full audit trail.

Design:
* All errors produce ``RunResult`` — the orchestrator never raises.
* Each attempt is logged to ``outputs/runs/<timestamp>.json``.
* Screenshots saved to ``outputs/evidence/<run_id>/attempt-N.png``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from komdigi_bot.config import Settings, get_settings
from komdigi_bot.solvers.base import BaseSolver, SolveAttempt, SolveStatus
from komdigi_bot.solvers.checkbox_grid import CheckboxGridSolver
from komdigi_bot.solvers.click_coords import ClickCoordsSolver
from komdigi_bot.solvers.fallback.api_solver import api_fallback_solver_from_page
from komdigi_bot.solvers.fallback.twocaptcha import TwoCaptchaClient
from komdigi_bot.solvers.image_ocr import ImageOCRSolver
from komdigi_bot.solvers.llm import LLMClient, llm_from_settings
from komdigi_bot.solvers.rotate_slide import RotateSlideSolver
from komdigi_bot.solvers.text_reasoning import TextReasoningSolver
from komdigi_bot.stealth.browser import StealthBrowser
from komdigi_bot.triage.detector import CaptchaDetector
from komdigi_bot.triage.router import CaptchaRouter, RoutingResult

logger = logging.getLogger(__name__)

_OUTPUTS_ROOT = Path("outputs")
_RUNS_DIR = _OUTPUTS_ROOT / "runs"
_EVIDENCE_DIR = _OUTPUTS_ROOT / "evidence"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Full result of one orchestrator run (one target URL)."""

    run_id: str
    url: str
    family: str
    engine: str
    final_status: SolveStatus
    attempts: list[SolveAttempt] = field(default_factory=list)
    total_latency_ms: float = 0.0
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def passed(self) -> bool:
        return self.final_status == SolveStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "url": self.url,
            "family": self.family,
            "engine": self.engine,
            "final_status": self.final_status.value,
            "passed": self.passed,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "attempt_count": len(self.attempts),
            "attempts": [
                {
                    "family": a.family,
                    "engine": a.engine,
                    "status": a.status.value,
                    "answer": a.answer,
                    "message": a.message,
                    "latency_ms": round(a.latency_ms, 1),
                    "llm_model": a.llm_model,
                    "screenshot": a.screenshot_path,
                }
                for a in self.attempts
            ],
            "error": self.error,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Solver registry
# ---------------------------------------------------------------------------


def _build_solver_registry(llm: LLMClient) -> dict[str, BaseSolver]:
    """Map engine keys → solver instances."""
    return {
        "text_reasoning": TextReasoningSolver(llm),
        "image_ocr": ImageOCRSolver(llm),
        "click_coords": ClickCoordsSolver(llm),
        "rotate_slide": RotateSlideSolver(llm),
        "checkbox_grid": CheckboxGridSolver(llm),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Orchestrate detection + solving for a single target URL.

    Args:
        settings: Loaded settings (defaults to ``get_settings()``).
        max_retries: In-house solver retry budget before API fallback.
        headless: Override headless mode (defaults to ``settings.stealth.headless``).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        max_retries: int = 3,
        headless: bool | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._max_retries = max_retries
        self._headless = headless

        # Override headless if requested
        if headless is not None:
            import copy
            cfg = copy.copy(self._settings.stealth)
            cfg.headless = headless
            self._stealth_cfg = cfg
        else:
            self._stealth_cfg = self._settings.stealth

        # Build LLM client (may be unconfigured — solvers handle gracefully)
        try:
            self._llm: LLMClient | None = llm_from_settings()
        except Exception:  # noqa: BLE001
            logger.warning("LLM client not configured — in-house solvers disabled")
            self._llm = None

        # Build 2captcha client if key available
        self._twocaptcha: TwoCaptchaClient | None = None
        with contextlib.suppress(Exception):
            if self._settings.twocaptcha_api_key:
                self._twocaptcha = TwoCaptchaClient(api_key=self._settings.twocaptcha_api_key)

        # Solver registry (requires LLM)
        self._registry: dict[str, BaseSolver] = {}
        if self._llm:
            self._registry = _build_solver_registry(self._llm)

        # Router
        self._router = CaptchaRouter(
            detector=CaptchaDetector(),
            jev_client=None,  # Jev optional — requires key
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, url: str) -> RunResult:
        """Navigate to *url*, detect, solve, and return a :class:`RunResult`."""
        run_id = uuid.uuid4().hex[:12]
        t0 = time.monotonic()
        evidence_dir = _EVIDENCE_DIR / run_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Orchestrator[%s]: starting run for %s", run_id, url)

        result = RunResult(
            run_id=run_id,
            url=url,
            family="unknown",
            engine="unknown",
            final_status=SolveStatus.FAIL,
        )

        try:
            with StealthBrowser(config=self._stealth_cfg) as page:
                result = self._run_with_page(page, url, run_id, evidence_dir, t0)
        except Exception as exc:  # noqa: BLE001
            logger.error("Orchestrator[%s]: unhandled exception: %s", run_id, exc)
            result.error = str(exc)
            result.final_status = SolveStatus.FAIL

        result.total_latency_ms = (time.monotonic() - t0) * 1000
        self._write_run_log(result)
        logger.info(
            "Orchestrator[%s]: done status=%s latency=%.0fms",
            run_id,
            result.final_status.value,
            result.total_latency_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_with_page(
        self,
        page: Page,
        url: str,
        run_id: str,
        evidence_dir: Path,
        t0: float,
    ) -> RunResult:
        # Navigate
        _ = page.goto(url, wait_until="networkidle", timeout=30_000)
        time.sleep(1.0)

        # Triage
        html = page.content()
        routing: RoutingResult = self._router.route(html, page_url=url)
        logger.info(
            "Orchestrator[%s]: triage family=%s engine=%s confidence=%.2f",
            run_id, routing.family, routing.engine, routing.confidence,
        )

        result = RunResult(
            run_id=run_id,
            url=url,
            family=routing.family,
            engine=routing.engine,
            final_status=SolveStatus.FAIL,
        )

        # No captcha detected
        if routing.family == "none":
            result.final_status = SolveStatus.SKIP
            return result

        # Determine solver
        solver = self._registry.get(routing.engine)

        # In-house retry loop
        if solver:
            for attempt_n in range(1, self._max_retries + 1):
                logger.info("Orchestrator[%s]: attempt %d/%d engine=%s", run_id, attempt_n, self._max_retries, routing.engine)
                attempt = solver.solve(page, evidence_dir)
                result.attempts.append(attempt)

                if attempt.passed:
                    result.final_status = SolveStatus.PASS
                    return result

                if attempt.status == SolveStatus.SKIP:
                    break  # escalate immediately on SKIP

                # Reload page before retry
                if attempt_n < self._max_retries:
                    time.sleep(1.5)
                    with contextlib.suppress(Exception):
                        _ = page.reload(wait_until="networkidle", timeout=20_000)

        # API fallback (hybrid policy only)
        if (
            self._settings.solver_policy == "hybrid"
            and self._twocaptcha
            and routing.engine == "api_fallback"
        ):
            logger.info("Orchestrator[%s]: escalating to 2captcha API", run_id)
            fallback = api_fallback_solver_from_page(page, routing.family, self._twocaptcha)
            attempt = fallback.solve(page, evidence_dir)
            result.attempts.append(attempt)
            if attempt.passed:
                result.final_status = SolveStatus.PASS

        return result

    def _write_run_log(self, result: RunResult) -> None:
        _RUNS_DIR.mkdir(parents=True, exist_ok=True)
        path = _RUNS_DIR / f"{result.run_id}.json"
        path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        logger.debug("Run log written to %s", path)
