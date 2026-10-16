"""API fallback solver — dispatches to 2captcha for heavy families.

Supported families via this solver:
    - turnstile      → TurnstileTaskProxyless → inject token into CF hidden input
    - arkose         → FunCaptchaTaskProxyless → inject token
    - geetest        → GeeTestTaskProxyless → inject validate/seccode/challenge
    - recaptcha      → RecaptchaV2TaskProxyless → inject gRecaptchaResponse

Token injection strategy:
    Execute JS ``grecaptcha.callback(token)`` or set the value of the hidden
    input that Cloudflare/reCAPTCHA reads. Then click the submit button.

This solver does NOT launch its own browser — it receives the live ``page``
from the orchestrator (already navigated to the target URL).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from playwright.sync_api import Page

from komdigi_bot.solvers.base import CAPTCHA_PASS_MARKER, BaseSolver, SolveAttempt, SolveStatus
from komdigi_bot.solvers.fallback.twocaptcha import (
    TwoCaptchaClient,
    TwoCaptchaError,
    TwoCaptchaTimeout,
)

logger = logging.getLogger(__name__)

_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Check')",
    "button:has-text('Submit')",
    "button:has-text('Verify')",
]


class APIFallbackSolver(BaseSolver):
    """Solve captcha families via 2captcha external API.

    Args:
        client: Configured :class:`~komdigi_bot.solvers.fallback.twocaptcha.TwoCaptchaClient`.
        family: The captcha family this instance is handling.
        site_key: The public site key extracted from the page.
        page_url: The URL of the page being solved.
    """

    ENGINE_KEY = "api_fallback"

    def __init__(
        self,
        client: TwoCaptchaClient,
        family: str,
        site_key: str,
        page_url: str,
    ) -> None:
        self._client = client
        self._family = family
        self._site_key = site_key
        self._page_url = page_url

    def solve(self, page: Page, evidence_dir: Path) -> SolveAttempt:
        t0 = time.monotonic()

        dispatcher = {
            "turnstile": self._solve_turnstile,
            "arkose": self._solve_arkose,
            "geetest": self._solve_geetest,
            "recaptcha": self._solve_recaptcha,
        }

        handler = dispatcher.get(self._family)
        if not handler:
            return SolveAttempt(
                family=self._family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.SKIP,
                message=f"Family {self._family!r} not supported by API fallback",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        try:
            token = handler()
        except TwoCaptchaTimeout as exc:
            return SolveAttempt(
                family=self._family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"2captcha timeout: {exc}",
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        except TwoCaptchaError as exc:
            return SolveAttempt(
                family=self._family,
                engine=self.ENGINE_KEY,
                status=SolveStatus.FAIL,
                message=f"2captcha error: {exc}",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        # Inject token into page and submit
        self._inject_token(page, token)
        time.sleep(1.5)
        self._click_submit(page)
        time.sleep(2.0)

        screenshot = self._take_screenshot(page, evidence_dir, f"{self._family}-fallback.png")
        passed = self._check_success(page)

        return SolveAttempt(
            family=self._family,
            engine=self.ENGINE_KEY,
            status=SolveStatus.PASS if passed else SolveStatus.FAIL,
            answer=token[:40] + "…" if len(token) > 40 else token,
            message=CAPTCHA_PASS_MARKER
            if passed
            else "Token injected but success marker not found",
            screenshot_path=screenshot,
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    # ------------------------------------------------------------------
    # Family-specific task submitters
    # ------------------------------------------------------------------

    def _solve_turnstile(self) -> str:
        logger.info("APIFallback[turnstile]: submitting to 2captcha …")
        return self._client.solve_turnstile(
            website_url=self._page_url,
            website_key=self._site_key,
        )

    def _solve_arkose(self) -> str:
        logger.info("APIFallback[arkose]: submitting to 2captcha …")
        return self._client.solve_funcaptcha(
            website_url=self._page_url,
            website_public_key=self._site_key,
        )

    def _solve_geetest(self) -> str:
        """GeeTest requires gt + challenge params from page JS — return validate token."""
        logger.info("APIFallback[geetest]: submitting to 2captcha …")
        # gt/challenge are extracted by the orchestrator from page JS;
        # fallback to site_key as gt when challenge not separately provided
        gt, _, challenge = self._site_key.partition("|")
        result = self._client.solve_geetest(
            website_url=self._page_url,
            gt=gt,
            challenge=challenge or gt,
        )
        return result.get("geetest_validate", "")

    def _solve_recaptcha(self) -> str:
        logger.info("APIFallback[recaptcha]: submitting to 2captcha …")
        return self._client.solve_recaptcha_v2(
            website_url=self._page_url,
            website_key=self._site_key,
        )

    # ------------------------------------------------------------------
    # Token injection
    # ------------------------------------------------------------------

    def _inject_token(self, page: Page, token: str) -> None:
        """Inject the solved token into the page via JS."""
        if not token:
            logger.warning("APIFallback: empty token — skipping injection")
            return

        js_injectors = [
            # Cloudflare Turnstile callback
            f"if(window.turnstile){{window.turnstile.set('{token}');}}",
            # reCAPTCHA v2 callback
            f"if(window.___grecaptcha_cfg){{document.getElementById('g-recaptcha-response').value='{token}';}}",
            # Generic hidden input
            f'(function(){{var i=document.querySelector(\'[name="cf-turnstile-response"],[name="g-recaptcha-response"],[name="h-captcha-response"]\');if(i){{i.value=\'{token}\';}}}})();',
        ]

        for js in js_injectors:
            try:
                _ = page.evaluate(js)
            except Exception:
                pass  # silently try next

        logger.info("APIFallback: token injected (len=%d)", len(token))

    def _click_submit(self, page: Page) -> None:
        for sel in _SUBMIT_SELECTORS:
            try:
                btn = page.locator(sel).first
                if btn.is_visible():
                    btn.click()
                    return
            except Exception:
                continue


def api_fallback_solver_from_page(
    page: Page,
    family: str,
    client: TwoCaptchaClient,
) -> APIFallbackSolver:
    """Extract site key from the live page and construct an :class:`APIFallbackSolver`.

    Supports Turnstile, Arkose, reCAPTCHA v2/v3/enterprise site key extraction.
    """
    site_key = _extract_site_key(page, family)
    page_url = page.url
    return APIFallbackSolver(
        client=client,
        family=family,
        site_key=site_key,
        page_url=page_url,
    )


def _extract_site_key(page: Page, family: str) -> str:
    """Extract the public site key for the given captcha family from the page HTML."""
    html = page.content()

    import re

    patterns: dict[str, list[str]] = {
        "turnstile": [
            r'data-sitekey=["\']([0-9a-zA-Z_\-]+)["\']',
            r'sitekey:\s*["\']([0-9a-zA-Z_\-]+)["\']',
        ],
        "recaptcha": [
            r'data-sitekey=["\']([0-9a-zA-Z_\-]+)["\']',
            r'sitekey:\s*["\']([0-9a-zA-Z_\-]+)["\']',
        ],
        "arkose": [
            r'data-pkey=["\']([0-9a-zA-Z_\-]+)["\']',
            r'public_key:\s*["\']([0-9a-zA-Z_\-]+)["\']',
        ],
        "geetest": [
            r'captchaId:\s*["\']([0-9a-zA-Z]+)["\']',
            r'"gt":\s*["\']([0-9a-f]+)["\']',
        ],
    }

    for pattern in patterns.get(family, []):
        m = re.search(pattern, html)
        if m:
            logger.info("APIFallback: extracted site_key=%r for family=%s", m.group(1)[:20], family)
            return m.group(1)

    logger.warning("APIFallback: could not extract site_key for family=%s", family)
    return ""
