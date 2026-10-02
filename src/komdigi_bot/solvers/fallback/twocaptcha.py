"""2captcha API client — thin synchronous wrapper.

Handles task submission and polling for all heavy captcha families:
    - Cloudflare Turnstile   (``TurnstileTask`` / ``TurnstileTaskProxyless``)
    - Arkose Labs             (``FunCaptchaTask`` / ``FunCaptchaTaskProxyless``)
    - GeeTest v3 / v4        (``GeeTestTask``)
    - reCAPTCHA v3 / Enterprise (``RecaptchaV3Task``)

API contract: https://2captcha.com/api-docs
    POST https://api.2captcha.com/createTask  → {"taskId": 12345}
    POST https://api.2captcha.com/getTaskResult → {"status":"ready","solution":{...}}

Key values are read from settings at runtime — never hardcoded here.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.2captcha.com"
_DEFAULT_POLL_INTERVAL = 5.0   # seconds between status checks
_DEFAULT_MAX_WAIT = 120.0      # give up after 2 minutes


class TwoCaptchaError(RuntimeError):
    """Raised on non-zero ``errorCode`` or unexpected schema from 2captcha."""


class TwoCaptchaTimeout(TimeoutError):
    """Raised when the task does not finish within ``max_wait`` seconds."""


class TwoCaptchaClient:
    """Synchronous 2captcha API client.

    Args:
        api_key: Value of ``TWOCAPTCHA_API_KEY`` from ``.env``.
        poll_interval: Seconds to wait between ``getTaskResult`` polls.
        max_wait: Maximum seconds to wait before :class:`TwoCaptchaTimeout`.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        max_wait: float = _DEFAULT_MAX_WAIT,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise TwoCaptchaError(
                "TWOCAPTCHA_API_KEY is empty — obtain one from 2captcha.com "
                "and add it to .env"
            )
        self._api_key = api_key
        self._poll_interval = poll_interval
        self._max_wait = max_wait
        self._timeout = timeout

    # ------------------------------------------------------------------
    # High-level helpers (one per captcha family)
    # ------------------------------------------------------------------

    def solve_turnstile(
        self,
        website_url: str,
        website_key: str,
        page_action: str = "",
    ) -> str:
        """Submit a Turnstile task and return the ``token`` string."""
        task: dict[str, Any] = {
            "type": "TurnstileTaskProxyless",
            "websiteURL": website_url,
            "websiteKey": website_key,
        }
        if page_action:
            task["pageAction"] = page_action
        solution = self._submit_and_poll(task)
        return str(solution.get("token", solution.get("cfClearance", "")))

    def solve_funcaptcha(
        self,
        website_url: str,
        website_public_key: str,
        data: str = "",
    ) -> str:
        """Submit a FunCaptcha (Arkose) task and return the ``token``."""
        task: dict[str, Any] = {
            "type": "FunCaptchaTaskProxyless",
            "websiteURL": website_url,
            "websitePublicKey": website_public_key,
        }
        if data:
            task["data"] = data
        solution = self._submit_and_poll(task)
        return str(solution.get("token", ""))

    def solve_geetest(
        self,
        website_url: str,
        gt: str,
        challenge: str,
        geetest_api_server_subdomain: str = "",
    ) -> dict[str, str]:
        """Submit a GeeTest v3 task and return the solution dict."""
        task: dict[str, Any] = {
            "type": "GeeTestTaskProxyless",
            "websiteURL": website_url,
            "gt": gt,
            "challenge": challenge,
        }
        if geetest_api_server_subdomain:
            task["geetestApiServerSubdomain"] = geetest_api_server_subdomain
        solution = self._submit_and_poll(task)
        return {
            "geetest_validate": str(solution.get("validate", "")),
            "geetest_seccode": str(solution.get("seccode", "")),
            "geetest_challenge": str(solution.get("challenge", challenge)),
        }

    def solve_recaptcha_v3(
        self,
        website_url: str,
        website_key: str,
        page_action: str = "verify",
        min_score: float = 0.3,
    ) -> str:
        """Submit a reCAPTCHA v3 task and return the ``gRecaptchaResponse`` token."""
        task: dict[str, Any] = {
            "type": "RecaptchaV3TaskProxyless",
            "websiteURL": website_url,
            "websiteKey": website_key,
            "pageAction": page_action,
            "minScore": min_score,
        }
        solution = self._submit_and_poll(task)
        return str(solution.get("gRecaptchaResponse", ""))

    def solve_recaptcha_v2(
        self,
        website_url: str,
        website_key: str,
    ) -> str:
        """Submit a reCAPTCHA v2 task and return the ``gRecaptchaResponse`` token."""
        task: dict[str, Any] = {
            "type": "RecaptchaV2TaskProxyless",
            "websiteURL": website_url,
            "websiteKey": website_key,
        }
        solution = self._submit_and_poll(task)
        return str(solution.get("gRecaptchaResponse", ""))

    # ------------------------------------------------------------------
    # Core submit + poll
    # ------------------------------------------------------------------

    def _submit_and_poll(self, task: dict[str, Any]) -> dict[str, Any]:
        """Submit *task* and poll until complete. Returns the ``solution`` dict."""
        task_id = self._create_task(task)
        logger.info("2captcha: taskId=%s type=%s", task_id, task.get("type"))

        deadline = time.monotonic() + self._max_wait
        while time.monotonic() < deadline:
            time.sleep(self._poll_interval)
            result = self._get_task_result(task_id)
            status = result.get("status")
            if status == "ready":
                solution: dict[str, Any] = result.get("solution", {})
                logger.info("2captcha: taskId=%s solved", task_id)
                return solution
            if status == "processing":
                logger.debug("2captcha: taskId=%s still processing …", task_id)
                continue
            # Unexpected status
            raise TwoCaptchaError(f"Unexpected 2captcha status {status!r}: {result}")

        raise TwoCaptchaTimeout(
            f"2captcha task {task_id} did not complete within {self._max_wait:.0f}s"
        )

    def _create_task(self, task: dict[str, Any]) -> int:
        body = {"clientKey": self._api_key, "task": task}
        resp = httpx.post(
            f"{_BASE}/createTask",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
            timeout=self._timeout,
        )
        data = self._parse(resp)
        task_id = data.get("taskId")
        if not task_id:
            raise TwoCaptchaError(f"2captcha createTask returned no taskId: {data}")
        return int(task_id)

    def _get_task_result(self, task_id: int) -> dict[str, Any]:
        body = {"clientKey": self._api_key, "taskId": task_id}
        resp = httpx.post(
            f"{_BASE}/getTaskResult",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
            timeout=self._timeout,
        )
        return self._parse(resp)

    def _parse(self, resp: httpx.Response) -> dict[str, Any]:
        if not resp.is_success:
            raise TwoCaptchaError(f"2captcha HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data: dict[str, Any] = resp.json()
        except json.JSONDecodeError as exc:
            raise TwoCaptchaError(f"2captcha non-JSON response: {resp.text[:200]}") from exc
        err = data.get("errorCode") or data.get("error_code")
        if err:
            raise TwoCaptchaError(f"2captcha errorCode={err}: {data.get('errorDescription', '')}")
        return data
