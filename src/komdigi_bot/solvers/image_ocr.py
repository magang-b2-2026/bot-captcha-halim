"""Image/Normal CAPTCHA solver using vision LLM OCR.

Target: ``https://2captcha.com/demo/normal``

Approach:
1. Locate the CAPTCHA image element.
2. Take a cropped screenshot of that element.
3. Send to vision LLM with transcription prompt.
4. Type the transcribed text character-by-character.
5. Submit and assert success.

Proven pattern from research session: vision LLM transcribed "W9H5K" correctly
from the normal captcha image on the first attempt.
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

_IMAGE_SELECTORS = [
    "#htest_image",
    "img#htest_image",
    "img[src*='veriword' i]",
    "img[alt*='captcha' i]",
    "img[src*='captcha' i]",
    "#captcha",
    "#captchaImage",
    ".captcha img",
    "img.captcha",
    "img[alt*='normal captcha' i]",
    "img[src*='get_captcha' i]",
    "img[src*='captcha.php' i]",
]

_INPUT_SELECTORS = [
    "#vericode",
    "input#vericode",
    "input[name='vericode']",
    "input[name*='captcha' i]",
    "input[id*='captcha' i]",
    "input[name*='keystring' i]",
    "input[placeholder*='answer' i]",
    "input[placeholder*='code' i]",
    "input[type='text']",
]

_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "button:has-text('Check')",
    "button:has-text('Submit')",
    "input[type='submit']",
    "input[value*='submit' i]",
    "input[value*='send' i]",
]

_VISION_SYSTEM = (
    "You are a high-accuracy CAPTCHA decoding engine. "
    "If the image contains standard text/letters/digits, return ONLY the characters shown with no spaces or punctuation. "
    "If the image contains an arithmetic problem or equation (e.g. '3 + 4' or '7 - 2 = ?'), calculate and return ONLY the resulting number."
)


class ImageOCRSolver(BaseSolver):
    """Solve image/normal CAPTCHA via vision LLM transcription."""

    ENGINE_KEY = "image_ocr"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def solve(self, page: Page, evidence_dir: Path) -> SolveAttempt:
        t0 = time.monotonic()
        family = "image"

        # ------------------------------------------------------------------
        # 1. Find and screenshot the captcha image element
        # ------------------------------------------------------------------
        img_path = self._screenshot_captcha_element(page, evidence_dir)
        if img_path is None:
            # Fallback: screenshot full viewport
            img_path = evidence_dir / "image-full.png"
            img_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                _ = page.screenshot(path=str(img_path))
            except Exception as exc:
                return SolveAttempt(
                    family=family,
                    engine=self.ENGINE_KEY,
                    status=SolveStatus.SKIP,
                    message=f"Could not screenshot: {exc}",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

        # ------------------------------------------------------------------
        # 2. Vision LLM transcription
        # ------------------------------------------------------------------
        try:
            raw = self._llm.ask_vision(
                image_path=img_path,
                prompt=(
                    "Transcribe the CAPTCHA text in this image. "
                    "If it is an arithmetic math equation (e.g. 5+3 or 9-4), solve it and return ONLY the numeric result. "
                    "Otherwise return ONLY the exact characters shown, with no spaces."
                ),
                system=_VISION_SYSTEM,
            )
        except Exception as exc:
            logger.error("ImageOCR: LLM vision call failed: %s", exc)
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"Vision LLM error: {exc}",
                screenshot_path=str(img_path),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        # Parse: keep only alphanumeric characters
        answer = re.sub(r"[^A-Za-z0-9]", "", raw).strip()
        logger.info("ImageOCR: raw=%r answer=%r", raw, answer)

        if not answer:
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"Vision model returned unparseable response: {raw!r}",
                screenshot_path=str(img_path),
                latency_ms=(time.monotonic() - t0) * 1000,
                llm_model=self._llm._vision_model,
            )

        # ------------------------------------------------------------------
        # 3. Type the answer
        # ------------------------------------------------------------------
        inp = self._find_input(page)
        if not inp:
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.SKIP,
                message="Answer input field not found",
                screenshot_path=str(img_path),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        try:
            inp.click()
            inp.press_sequentially(answer, delay=70)
            time.sleep(0.4)
        except Exception as exc:
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"Typing error: {exc}",
                screenshot_path=str(img_path),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        # ------------------------------------------------------------------
        # 4. Fill companion fields (if required by demo form) and submit
        # ------------------------------------------------------------------
        self._fill_companion_fields(page)
        self._click_submit(page)
        time.sleep(2.0)
        final_screenshot = self._take_screenshot(page, evidence_dir, "image-solved.png")
        passed = self._check_success(page)

        return SolveAttempt(
            family=family,
            engine=self.ENGINE_KEY,
            status=SolveStatus.PASS if passed else SolveStatus.FAIL,
            answer=answer,
            message=CAPTCHA_PASS_MARKER if passed else f"Wrong answer: {answer!r}",
            screenshot_path=final_screenshot,
            latency_ms=(time.monotonic() - t0) * 1000,
            llm_model=self._llm._vision_model,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fill_companion_fields(self, page: Page) -> None:
        """Populate empty companion fields (e.g. required textarea message on democaptcha)."""
        try:
            textareas = page.locator("textarea").all()
            for ta in textareas:
                if ta.is_visible():
                    val = ta.input_value() if hasattr(ta, "input_value") else ""
                    if not val or not str(val).strip():
                        ta.fill("Automated QA inquiry verification.")
                        logger.info("ImageOCR: populated empty companion textarea")
        except Exception as exc:
            logger.debug("ImageOCR: companion textarea fill skipped: %s", exc)

    def _screenshot_captcha_element(self, page: Page, evidence_dir: Path) -> Path | None:
        for sel in _IMAGE_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    path = evidence_dir / "captcha-image.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _ = loc.screenshot(path=str(path))
                    logger.info("ImageOCR: captured element screenshot via %s", sel)
                    return path
            except Exception:
                continue
        return None

    def _find_input(self, page: Page):  # type: ignore[return]
        for sel in _INPUT_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

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
