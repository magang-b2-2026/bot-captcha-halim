"""Rotate/Slide CAPTCHA solver using vision LLM + human drag.

Target: ``https://2captcha.com/demo/rotatecaptcha``

Approach:
1. Screenshot the rotatable puzzle image.
2. Ask vision LLM: "By how many degrees should this be rotated clockwise
   to appear upright?"
3. Map degrees → pixel drag distance on the slider/rotator.
4. Execute human-like drag (bezier trajectory) via StealthBrowser.human_drag.
5. Submit and check.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from playwright.sync_api import FloatRect, Page

from komdigi_bot.solvers.base import CAPTCHA_PASS_MARKER, BaseSolver, SolveAttempt, SolveStatus
from komdigi_bot.solvers.llm import LLMClient, LLMParseError

logger = logging.getLogger(__name__)

_ROTATE_IMG_SELECTORS = [
    "[class*='rotatecaptcha'] img",
    "[class*='rotate'] img",
    "img[class*='captcha']",
    "img[id*='rotate']",
]

_SLIDER_SELECTORS = [
    "input[type='range']",
    "[class*='slider']",
    "[class*='rotate-slider']",
]

_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "button:has-text('Check')",
    "button:has-text('Submit')",
    "input[type='submit']",
]

_VISION_SYSTEM = (
    "You are a CAPTCHA rotation solver. "
    "Look at the image and determine how many degrees clockwise it needs to be "
    "rotated so the main subject appears upright. "
    "Return ONLY an integer between 0 and 359. Example: 90"
)


def _parse_angle(text: str) -> int:
    """Extract a rotation angle (degrees) from LLM response."""
    m = re.search(r"\b(\d{1,3})\b", text)
    if m:
        angle = int(m.group(1))
        if 0 <= angle <= 359:
            return angle
    raise LLMParseError(f"Could not parse angle from: {text!r}")


def _degrees_to_drag_px(degrees: int, slider_width: float = 200.0) -> float:
    """Map rotation degrees to a horizontal slider drag distance in pixels.

    Assumes the slider represents a full 360° rotation across its width.
    """
    return (degrees / 360.0) * slider_width


class RotateSlideSolver(BaseSolver):
    """Solve rotate/slide puzzle CAPTCHA."""

    ENGINE_KEY = "rotate_slide"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def solve(self, page: Page, evidence_dir: Path) -> SolveAttempt:
        t0 = time.monotonic()
        family = "rotate"

        # ------------------------------------------------------------------
        # 1. Screenshot the puzzle image
        # ------------------------------------------------------------------
        img_path, img_box = self._screenshot_puzzle(page, evidence_dir)

        # ------------------------------------------------------------------
        # 2. Ask vision LLM for rotation angle
        # ------------------------------------------------------------------
        try:
            raw = self._llm.ask_vision(
                image_path=img_path,
                prompt=(
                    "How many degrees clockwise must this image be rotated "
                    "so the subject looks upright? Return only an integer 0-359."
                ),
                system=_VISION_SYSTEM,
            )
        except Exception as exc:
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"Vision LLM error: {exc}",
                screenshot_path=str(img_path),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        try:
            angle = _parse_angle(raw)
        except LLMParseError as exc:
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=str(exc),
                screenshot_path=str(img_path),
                latency_ms=(time.monotonic() - t0) * 1000,
                llm_model=self._llm._vision_model,
            )

        logger.info("RotateSlide: angle=%d°", angle)

        # ------------------------------------------------------------------
        # 3. Find slider / rotator control and drag
        # ------------------------------------------------------------------
        slider_box = self._find_slider_box(page)
        if slider_box:
            drag_px = _degrees_to_drag_px(angle, slider_width=slider_box["width"])
            self._drag(page, slider_box, delta_x=drag_px, delta_y=0.0)
        elif img_box:
            # No slider found — try dragging the image itself (rotator wheel)
            drag_px = _degrees_to_drag_px(angle, slider_width=img_box["width"])
            self._drag(page, img_box, delta_x=drag_px, delta_y=0.0)
        else:
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.SKIP,
                message="No slider or rotatable element found",
                screenshot_path=str(img_path),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        time.sleep(0.5)

        # ------------------------------------------------------------------
        # 4. Submit and check
        # ------------------------------------------------------------------
        self._click_submit(page)
        time.sleep(1.5)
        final_shot = self._take_screenshot(page, evidence_dir, "rotate-solved.png")
        passed = self._check_success(page)

        return SolveAttempt(
            family=family,
            engine=self.ENGINE_KEY,
            status=SolveStatus.PASS if passed else SolveStatus.FAIL,
            answer=f"{angle}deg",
            message=CAPTCHA_PASS_MARKER if passed else f"Rotation {angle}° did not pass",
            screenshot_path=final_shot,
            latency_ms=(time.monotonic() - t0) * 1000,
            llm_model=self._llm._vision_model,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _screenshot_puzzle(self, page: Page, evidence_dir: Path):  # type: ignore[return]
        img_path = evidence_dir / "rotate-puzzle.png"
        img_path.parent.mkdir(parents=True, exist_ok=True)
        for sel in _ROTATE_IMG_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    box = loc.bounding_box()
                    _ = loc.screenshot(path=str(img_path))
                    return img_path, box
            except Exception:
                continue
        _ = page.screenshot(path=str(img_path))
        return img_path, None

    def _find_slider_box(self, page: Page):  # type: ignore[return]
        for sel in _SLIDER_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    return loc.bounding_box()
            except Exception:
                continue
        return None

    def _drag(self, page: Page, box: FloatRect, delta_x: float, delta_y: float) -> None:
        """Human-like drag with ease-in-out and jitter."""
        import random

        rng = random.Random()
        sx = box["x"] + box["width"] / 2
        sy = box["y"] + box["height"] / 2
        page.mouse.move(sx, sy)
        time.sleep(0.12)
        page.mouse.down()
        time.sleep(0.06)
        steps = max(12, int(abs(delta_x + delta_y) // 5))
        for i in range(1, steps + 1):
            t = i / steps
            ease = t * t * (3 - 2 * t)  # smooth-step
            jx = rng.uniform(-1.5, 1.5)
            jy = rng.uniform(-1.0, 1.0)
            page.mouse.move(sx + delta_x * ease + jx, sy + delta_y * ease + jy)
            time.sleep(rng.uniform(0.01, 0.03))
        page.mouse.up()
        time.sleep(0.2)

    def _click_submit(self, page: Page) -> None:
        for sel in _SUBMIT_SELECTORS:
            try:
                btn = page.locator(sel).first
                if btn.is_visible():
                    btn.click()
                    return
            except Exception:
                continue
