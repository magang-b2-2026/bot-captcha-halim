"""Checkbox/Grid CAPTCHA solver (reCAPTCHA v2 / hCaptcha grid pattern).

Target: ``https://2captcha.com/demo/recaptcha-v2``

Approach:
1. Click the "I'm not a robot" checkbox to trigger the image grid challenge.
2. Screenshot the grid challenge iframe content.
3. Ask vision LLM: which grid cells match the requested category?
4. Click each matching cell using human-like clicks.
5. Click "VERIFY" / "Next" until the challenge passes.
6. Assert success.

Note: reCAPTCHA iframes require that the stealth layer is active (todo 3)
for them to render correctly.  This solver operates on the outer page;
grid interaction happens via Playwright frame locators.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Page

from komdigi_bot.solvers.base import CAPTCHA_PASS_MARKER, BaseSolver, SolveAttempt, SolveStatus
from komdigi_bot.solvers.llm import LLMClient

logger = logging.getLogger(__name__)

_CHECKBOX_SELECTORS = [
    # reCAPTCHA v2 checkbox iframe
    "iframe[src*='recaptcha/api2/anchor']",
    "iframe[title*='reCAPTCHA']",
    # hCaptcha
    "iframe[src*='hcaptcha.com']",
    # Generic checkbox
    ".recaptcha-checkbox",
    "[id*='recaptcha']",
]

_VERIFY_SELECTORS = [
    "#recaptcha-verify-button",
    ".rc-button-default",
    "button:has-text('VERIFY')",
    "button:has-text('Verify')",
    "button:has-text('Next')",
]

_VISION_SYSTEM = (
    "You are a CAPTCHA grid solver. "
    "Look at the grid image and identify which cells (numbered left-to-right, "
    "top-to-bottom starting from 1) contain the specified object. "
    "Return ONLY a comma-separated list of cell numbers. Example: 1,4,7"
)


def _parse_cell_numbers(text: str) -> list[int]:
    """Extract cell numbers from LLM response."""
    numbers = re.findall(r"\b([1-9])\b", text)
    return sorted({int(n) for n in numbers})


class CheckboxGridSolver(BaseSolver):
    """Solve reCAPTCHA v2 / hCaptcha grid CAPTCHA."""

    ENGINE_KEY = "checkbox_grid"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def solve(self, page: Page, evidence_dir: Path) -> SolveAttempt:
        t0 = time.monotonic()
        family = "recaptcha"

        # ------------------------------------------------------------------
        # 1. Click the "I'm not a robot" checkbox
        # ------------------------------------------------------------------
        clicked_checkbox = self._click_checkbox(page)
        time.sleep(2.0)  # wait for challenge iframe to appear

        # ------------------------------------------------------------------
        # 2. Screenshot the challenge (try frame first, then viewport)
        # ------------------------------------------------------------------
        img_path = self._screenshot_challenge(page, evidence_dir)
        category = self._extract_category(page)
        logger.info("CheckboxGrid: category=%r", category)

        # ------------------------------------------------------------------
        # 3. Ask vision LLM which cells to click
        # ------------------------------------------------------------------
        try:
            raw = self._llm.ask_vision(
                image_path=img_path,
                prompt=(
                    f"This is a CAPTCHA grid. Select all cells that contain: "
                    f"{category or 'the specified object'}. "
                    "Number cells 1-9 left-to-right, top-to-bottom. "
                    "Return only comma-separated numbers."
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

        cells = _parse_cell_numbers(raw)
        logger.info("CheckboxGrid: LLM selected cells=%s", cells)

        # ------------------------------------------------------------------
        # 4. Click the selected cells in the grid
        # ------------------------------------------------------------------
        self._click_grid_cells(page, cells)
        time.sleep(0.8)

        # ------------------------------------------------------------------
        # 5. Click VERIFY
        # ------------------------------------------------------------------
        self._click_verify(page)
        time.sleep(2.5)

        final_shot = self._take_screenshot(page, evidence_dir, "grid-solved.png")
        passed = self._check_success(page)

        return SolveAttempt(
            family=family,
            engine=self.ENGINE_KEY,
            status=SolveStatus.PASS if passed else SolveStatus.FAIL,
            answer=f"cells:{','.join(map(str, cells))}",
            message=CAPTCHA_PASS_MARKER if passed else f"Grid cells {cells} did not pass",
            screenshot_path=final_shot,
            latency_ms=(time.monotonic() - t0) * 1000,
            llm_model=self._llm._vision_model,
            extra={"clicked_checkbox": clicked_checkbox, "category": category},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _click_checkbox(self, page: Page) -> bool:
        """Click the "I'm not a robot" checkbox. Returns True if clicked."""
        for sel in _CHECKBOX_SELECTORS:
            try:
                # Handle iframe
                if "iframe" in sel:
                    frames = page.frames
                    for frame in frames:
                        if "anchor" in (frame.url or "") or "hcaptcha" in (frame.url or ""):
                            checkbox = frame.locator(".recaptcha-checkbox, #checkbox").first
                            if checkbox.is_visible():
                                checkbox.click()
                                return True
                else:
                    loc = page.locator(sel).first
                    if loc.is_visible():
                        loc.click()
                        return True
            except Exception:
                continue
        return False

    def _screenshot_challenge(self, page: Page, evidence_dir: Path) -> Path:
        img_path = evidence_dir / "grid-challenge.png"
        img_path.parent.mkdir(parents=True, exist_ok=True)
        # Try to screenshot the bframe (challenge frame)
        for frame in page.frames:
            url = frame.url or ""
            if "bframe" in url or "challenge" in url or "hcaptcha" in url:
                try:
                    frame_loc = page.frame_locator(f"iframe[src*='{url.split('?')[0].split('/')[-1]}']")
                    _ = frame_loc.locator("body").screenshot(path=str(img_path))
                    return img_path
                except Exception:
                    pass
        # Fallback: full page screenshot
        try:
            _ = page.screenshot(path=str(img_path))
        except Exception:
            pass
        return img_path

    def _extract_category(self, page: Page) -> str:
        """Try to read the challenge instruction (e.g. 'Select all traffic lights')."""
        for frame in page.frames:
            try:
                url = frame.url or ""
                if "bframe" in url or "challenge" in url or "hcaptcha" in url:
                    el = frame.locator(".rc-imageselect-desc, .prompt-text").first
                    return el.inner_text().strip()
            except Exception:
                continue
        return ""

    def _click_grid_cells(self, page: Page, cells: list[int]) -> None:
        """Click cells by index in the challenge frame."""
        for frame in page.frames:
            url = frame.url or ""
            if "bframe" in url or "challenge" in url or "hcaptcha" in url:
                try:
                    tiles = frame.locator(".rc-imageselect-tile, .task-image").all()
                    for cell_num in cells:
                        idx = cell_num - 1
                        if 0 <= idx < len(tiles):
                            tiles[idx].click()
                            time.sleep(0.3)
                except Exception as exc:
                    logger.warning("CheckboxGrid: cell click error: %s", exc)
                return
        logger.warning("CheckboxGrid: challenge frame not found for cell clicking")

    def _click_verify(self, page: Page) -> None:
        # Try in frames first
        for frame in page.frames:
            url = frame.url or ""
            if "bframe" in url or "challenge" in url:
                for sel in _VERIFY_SELECTORS:
                    try:
                        btn = frame.locator(sel).first
                        if btn.is_visible():
                            btn.click()
                            return
                    except Exception:
                        continue
        # Fallback: outer page
        for sel in _VERIFY_SELECTORS:
            try:
                btn = page.locator(sel).first
                if btn.is_visible():
                    btn.click()
                    return
            except Exception:
                continue
