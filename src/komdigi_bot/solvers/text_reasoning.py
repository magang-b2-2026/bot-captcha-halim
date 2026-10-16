"""Text/math CAPTCHA solver using LLM reasoning.

Target: ``https://2captcha.com/demo/text``

Approach:
1. Locate the challenge question text on the page.
2. Send it to the LLM as a plain text reasoning prompt.
3. Type the answer human-like into the input field.
4. Click the Check button and assert success.

Proven pattern from research session: "What day of the week is it today?" →
LLM reasons "Friday" (or current day) → pressSequentially → submit → ✅.
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

# Selectors that tend to contain the challenge question on common text captcha pages
_QUESTION_SELECTORS = [
    ".captcha__question",
    ".text-captcha-question",
    "[class*='question']",
    "p",
    "label",
]

# Selector for the text input where the answer is typed
_INPUT_SELECTORS = [
    "input[name='text']",
    "input[placeholder*='answer' i]",
    "input[placeholder*='Answer' i]",
    "input[type='text']",
]

# Submit / check button selectors
_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Check')",
    "button:has-text('Submit')",
    "button:has-text('Verify')",
]

_SYSTEM_PROMPT = (
    "You are a CAPTCHA solver. "
    "Answer the question concisely — only the answer, no explanation, no punctuation."
)


class TextReasoningSolver(BaseSolver):
    """Solve plain text / math CAPTCHA via LLM reasoning."""

    ENGINE_KEY = "text_reasoning"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def solve(self, page: Page, evidence_dir: Path) -> SolveAttempt:
        t0 = time.monotonic()
        family = "text"

        # ------------------------------------------------------------------
        # 1. Extract question text
        # ------------------------------------------------------------------
        question = self._extract_question(page)
        if not question:
            logger.warning("TextReasoning: could not find question text on page")
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.SKIP,
                message="Question text not found",
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        logger.info("TextReasoning: question=%r", question)

        # ------------------------------------------------------------------
        # 2. Ask LLM
        # ------------------------------------------------------------------
        try:
            raw_answer = self._llm.ask_text(
                prompt=f"Solve this CAPTCHA question: {question}",
                system=_SYSTEM_PROMPT,
            )
        except Exception as exc:
            logger.error("TextReasoning: LLM call failed: %s", exc)
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"LLM error: {exc}",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        answer = raw_answer.strip().strip('"').strip("'")
        logger.info("TextReasoning: LLM answer=%r", answer)

        # ------------------------------------------------------------------
        # 3. Type answer
        # ------------------------------------------------------------------
        inp = self._find_input(page)
        if not inp:
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.SKIP,
                message="Answer input not found",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        try:
            inp.click()
            inp.press_sequentially(answer, delay=60)
            time.sleep(0.4)
        except Exception as exc:
            return SolveAttempt(
                family=family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"Type error: {exc}",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        # ------------------------------------------------------------------
        # 4. Submit and check
        # ------------------------------------------------------------------
        self._click_submit(page)
        time.sleep(1.5)
        screenshot = self._take_screenshot(page, evidence_dir, "text-attempt.png")
        passed = self._check_success(page)

        return SolveAttempt(
            family=family,
            engine=self.ENGINE_KEY,
            status=SolveStatus.PASS if passed else SolveStatus.FAIL,
            answer=answer,
            message=CAPTCHA_PASS_MARKER if passed else "Submit did not yield success marker",
            screenshot_path=screenshot,
            latency_ms=(time.monotonic() - t0) * 1000,
            llm_model=self._llm._reasoning_model,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_question(self, page: Page) -> str:
        for sel in _QUESTION_SELECTORS:
            try:
                els = page.locator(sel).all()
                for el in els:
                    text = el.inner_text().strip()
                    if text and (
                        "?" in text
                        or any(
                            w in text.lower()
                            for w in ["what", "which", "solve", "calculate", "answer", "day"]
                        )
                    ):
                        return text
            except Exception:
                continue
        # Fallback: grab all visible text and look for a question
        try:
            full = page.content()
            matches = re.findall(r"([A-Z][^.!?<]{5,80}\?)", full)
            if matches:
                return matches[0]
        except Exception:
            pass
        return ""

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
