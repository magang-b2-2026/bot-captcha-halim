"""Base class and shared types for all captcha solver engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from playwright.sync_api import Page


class SolveStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"  # family not supported / widget not found


@dataclass
class SolveAttempt:
    """Result of one solver engine attempt."""

    family: str
    engine: str
    status: SolveStatus
    answer: str = ""              # the answer submitted (text, "x,y", "angle", etc.)
    message: str = ""            # human-readable result message
    screenshot_path: str = ""    # absolute path to evidence screenshot
    latency_ms: float = 0.0
    llm_model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == SolveStatus.PASS


# Canonical success message seen on 2captcha demo pages after correct solve
CAPTCHA_PASS_MARKER = "Captcha is passed successfully"

# Generic success indicators across various captcha demo and submission platforms
SUCCESS_MARKERS = [
    "captcha is passed successfully",
    "passed successfully",
    "passed!",
    "verification passed",
    "captcha passed",
    "correct captcha",
    "form submitted",
    "message has been sent",
    "congratulations",
    "success",
]


class BaseSolver:
    """Abstract base for all solver engines.

    Subclasses implement :meth:`solve` which takes the live Playwright
    ``page`` and returns a :class:`SolveAttempt`.

    The orchestrator calls :meth:`solve` and handles retries / rotation.
    """

    #: Subclasses declare which triage engine key they handle
    ENGINE_KEY: str = ""

    def solve(self, page: Page, evidence_dir: Path) -> SolveAttempt:
        raise NotImplementedError

    def _check_success(self, page: Page) -> bool:
        """Heuristic: look for canonical success text in page content."""
        try:
            content = page.content().lower()
            return any(marker in content for marker in SUCCESS_MARKERS)
        except Exception:
            return False

    def _take_screenshot(self, page: Page, evidence_dir: Path, name: str) -> str:
        """Save a screenshot and return its absolute path string."""
        path = evidence_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _ = page.screenshot(path=str(path))
        except Exception:
            pass
        return str(path)
