"""Click-coordinates CAPTCHA solver using vision LLM.

Target: ``https://2captcha.com/demo/clickcaptcha``

Approach:
1. Screenshot the click target area (canvas / image).
2. Send to vision LLM with instruction to return the click coordinates
   of the specified target object.
3. Parse the (x, y) coordinates from the model response.
4. Human-click at those coordinates using Playwright mouse.
5. Submit and check.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Page

from komdigi_bot.solvers.base import CAPTCHA_PASS_MARKER, BaseSolver, SolveAttempt, SolveStatus
from komdigi_bot.solvers.llm import LLMClient, LLMParseError

logger = logging.getLogger(__name__)

_CANVAS_SELECTORS = [
    "canvas",
    ".captcha-canvas",
    "img.click-captcha",
    "[class*='clickcaptcha']",
    "[class*='click-captcha']",
]

_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "button:has-text('Check')",
    "button:has-text('Submit')",
    "button:has-text('Verify')",
    "input[type='submit']",
]

_VISION_SYSTEM = (
    "You are a CAPTCHA solver that finds specific objects in images. "
    "Return ONLY a JSON object with 'x' and 'y' keys (integer pixel coordinates) "
    'indicating where to click. Example: {"x": 142, "y": 87}'
)


def _parse_coords(text: str) -> tuple[int, int]:
    """Extract (x, y) pixel coordinates from LLM response."""
    # Try JSON-style
    m = re.search(r'"x"\s*:\s*(\d+).*?"y"\s*:\s*(\d+)', text, re.DOTALL)
    if not m:
        m = re.search(r'"y"\s*:\s*(\d+).*?"x"\s*:\s*(\d+)', text, re.DOTALL)
        if m:
            return int(m.group(2)), int(m.group(1))
    if m:
        return int(m.group(1)), int(m.group(2))
    # Try plain "x, y" or "(x, y)"
    m2 = re.search(r"(\d+)\s*[,;]\s*(\d+)", text)
    if m2:
        return int(m2.group(1)), int(m2.group(2))
    raise LLMParseError(f"Could not parse coordinates from: {text!r}")


class ClickCoordsSolver(BaseSolver):
    """Solve click-coordinate CAPTCHA via vision LLM."""

    ENGINE_KEY = "click_coords"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def solve(self, page: Page, evidence_dir: Path) -> SolveAttempt:
        t0 = time.monotonic()
        family = "click"

        # ------------------------------------------------------------------
        # 1. Find and screenshot the click target area
        # ------------------------------------------------------------------
        target_loc, canvas_box = self._find_canvas(page)
        img_path = evidence_dir / "click-captcha.png"
        img_path.parent.mkdir(parents=True, exist_ok=True)

        if target_loc:
            try:
                _ = target_loc.screenshot(path=str(img_path))
            except Exception:
                _ = page.screenshot(path=str(img_path))
        else:
            _ = page.screenshot(path=str(img_path))

        # Get the instruction text (what to click on)
        instruction = self._get_instruction(page)
        logger.info("ClickCoords: instruction=%r", instruction)

        # ------------------------------------------------------------------
        # 2. Ask vision LLM for coordinates
        # ------------------------------------------------------------------
        prompt = (
            f"In this CAPTCHA image, find and return the pixel coordinates (x, y) "
            f"of: {instruction or 'the target object'}. "
            'Return ONLY a JSON object like {"x": 100, "y": 200}.'
        )

        try:
            raw = self._llm.ask_vision(
                image_path=img_path,
                prompt=prompt,
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

        # ------------------------------------------------------------------
        # 3. Parse coordinates and click
        # ------------------------------------------------------------------
        try:
            rel_x, rel_y = _parse_coords(raw)
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

        # If we screenshotted a sub-element, coordinates are relative to it;
        # add the element's page offset.
        click_x = rel_x
        click_y = rel_y
        if canvas_box:
            click_x = canvas_box["x"] + rel_x
            click_y = canvas_box["y"] + rel_y

        logger.info("ClickCoords: clicking at page coords (%d, %d)", click_x, click_y)

        try:
            page.mouse.move(click_x, click_y)
            time.sleep(0.15)
            page.mouse.click(click_x, click_y)
            time.sleep(0.5)
        except Exception as exc:
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"Click error: {exc}",
                screenshot_path=str(img_path),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        # ------------------------------------------------------------------
        # 4. Submit and check
        # ------------------------------------------------------------------
        self._click_submit(page)
        time.sleep(1.5)
        final_shot = self._take_screenshot(page, evidence_dir, "click-solved.png")
        passed = self._check_success(page)

        return SolveAttempt(
            family=family,
            engine=self.ENGINE_KEY,
            status=SolveStatus.PASS if passed else SolveStatus.FAIL,
            answer=f"{rel_x},{rel_y}",
            message=CAPTCHA_PASS_MARKER if passed else f"Click at ({rel_x},{rel_y}) did not pass",
            screenshot_path=final_shot,
            latency_ms=(time.monotonic() - t0) * 1000,
            llm_model=self._llm._vision_model,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_canvas(self, page: Page):  # type: ignore[return]
        for sel in _CANVAS_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    box = loc.bounding_box()
                    return loc, box
            except Exception:
                continue
        return None, None

    def _get_instruction(self, page: Page) -> str:
        try:
            for sel in ["p", ".captcha-instruction", "[class*='instruction']", "label"]:
                els = page.locator(sel).all()
                for el in els:
                    text = el.inner_text().strip()
                    if text and len(text) > 5:
                        return text
        except Exception:
            pass
        return ""

    def _click_submit(self, page: Page) -> None:
        for sel in _SUBMIT_SELECTORS:
            try:
                btn = page.locator(sel).first
                if btn.is_visible():
                    try:
                        btn.click(no_wait_after=True, timeout=5000)
                    except TypeError:
                        btn.click(timeout=5000)
                    return
            except Exception:
                continue
