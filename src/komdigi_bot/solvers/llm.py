"""OpenAI-compatible LLM provider abstraction.

Wraps any OpenAI-compatible endpoint (OpenCode key, local Ollama, etc.)
for use by the solver engines.  Model selection comes from config:

* ``LLM_BASE_URL``        — e.g. ``https://openrouter.ai/api/v1``
* ``LLM_API_KEY``         — API key (OpenCode / OpenRouter / etc.)
* ``LLM_MODEL_VISION``    — vision-capable model slug (pinned by benchmark)
* ``LLM_MODEL_REASONING`` — reasoning-only model slug

All methods are synchronous (Playwright is sync; mixing async would complicate
the stealth layer).

Design decisions:
* ``ask_text`` — plain text prompt, returns string answer.
* ``ask_vision`` — sends a base64-encoded screenshot + text prompt; returns
  the model response string.  Requires ``LLM_MODEL_VISION``.
* Parse errors in caller → re-raise as ``LLMParseError`` so orchestrator
  can count attempts and retry.
* Never silently swallows API errors — always re-raises with context.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMConfigError(RuntimeError):
    """Raised when required LLM config fields are empty."""


class LLMAPIError(RuntimeError):
    """Raised on non-2xx responses from the LLM endpoint."""


class LLMParseError(ValueError):
    """Raised when the model response cannot be parsed into the expected format."""


class LLMClient:
    """Synchronous client for any OpenAI-compatible chat-completion endpoint.

    Args:
        base_url: e.g. ``https://openrouter.ai/api/v1``
        api_key: Bearer token.
        vision_model: Model slug for vision tasks (MUST support image input).
        reasoning_model: Model slug for text-only reasoning tasks.
        timeout: HTTP timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        vision_model: str,
        reasoning_model: str,
        timeout: float = 60.0,
    ) -> None:
        if not base_url:
            raise LLMConfigError("LLM_BASE_URL is empty — set it in .env")
        if not api_key:
            raise LLMConfigError("LLM_API_KEY is empty — set it in .env")
        if not vision_model:
            raise LLMConfigError(
                "LLM_MODEL_VISION is empty — run benchmark harness (todo 9) to pin a model"
            )
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._vision_model = vision_model
        self._reasoning_model = reasoning_model or vision_model
        self._timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        # Fallback providers: list of (base_url, api_key) tried in order on failure
        self._fallbacks: list[tuple[str, str]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask_text(self, prompt: str, system: str = "") -> str:
        """Send a text-only prompt and return the model's reply string."""
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._reasoning_model,
            "messages": messages,
            "max_tokens": 256,
            "temperature": 0.0,
        }
        logger.debug("LLM text ask: model=%s prompt_len=%d", self._reasoning_model, len(prompt))
        return self._chat(payload)

    def ask_vision(
        self,
        image_path: str | Path,
        prompt: str,
        system: str = "",
    ) -> str:
        """Send an image + text prompt to the vision model.

        Args:
            image_path: Path to a PNG/JPEG screenshot.
            prompt: Instruction for the model.
            system: Optional system message.

        Returns:
            Raw model response string (caller parses).

        Raises:
            LLMConfigError: Vision model not configured.
            LLMAPIError: Non-2xx from the endpoint.
            FileNotFoundError: ``image_path`` does not exist.
        """
        img_bytes = Path(image_path).read_bytes()
        b64 = base64.b64encode(img_bytes).decode("ascii")
        # Detect image type from magic bytes
        mime = "image/png" if img_bytes[:4] == b"\x89PNG" else "image/jpeg"
        data_url = f"data:{mime};base64,{b64}"

        content: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": prompt},
        ]
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        payload = {
            "model": self._vision_model,
            "messages": messages,
            "max_tokens": 128,
            "temperature": 0.0,
        }
        logger.debug(
            "LLM vision ask: model=%s image=%s prompt_len=%d",
            self._vision_model,
            image_path,
            len(prompt),
        )
        return self._chat(payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _chat(self, payload: dict[str, Any]) -> str:
        """Send chat completion request with automatic fallback to secondary providers."""
        primary_url = f"{self._base_url}/chat/completions"

        # Build provider list: primary first, then each fallback
        providers: list[tuple[str, dict[str, str]]] = [
            (primary_url, self._headers)
        ]
        for fb_url, fb_key in self._fallbacks:
            providers.append((
                f"{fb_url.rstrip('/')}/chat/completions",
                {"Authorization": f"Bearer {fb_key}", "Content-Type": "application/json"},
            ))

        last_error: Exception | None = None
        for attempt_idx, (url, headers) in enumerate(providers):
            try:
                resp = httpx.post(
                    url,
                    headers=headers,
                    content=json.dumps(payload),
                    timeout=self._timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = LLMAPIError(f"LLM request timed out after {self._timeout}s (provider #{attempt_idx})")
                logger.warning("LLM provider #%d timeout, trying fallback…", attempt_idx)
                continue
            except httpx.RequestError as exc:
                last_error = LLMAPIError(f"LLM connection error (provider #{attempt_idx}): {exc}")
                logger.warning("LLM provider #%d connection error, trying fallback…", attempt_idx)
                continue

            if not resp.is_success:
                last_error = LLMAPIError(f"LLM API {resp.status_code} (provider #{attempt_idx}): {resp.text[:300]}")
                logger.warning("LLM provider #%d returned %s, trying fallback…", attempt_idx, resp.status_code)
                continue

            try:
                body = resp.json()
                return str(body["choices"][0]["message"]["content"]).strip()
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                last_error = LLMAPIError(
                    f"LLM response schema unexpected (provider #{attempt_idx}): {exc} — raw={resp.text[:200]}"
                )
                continue

        # All providers exhausted
        raise last_error or LLMAPIError("All LLM providers failed — check .env configuration")


def llm_from_settings() -> LLMClient:
    """Construct :class:`LLMClient` from the process-wide settings.

    Wires Vikey.ai as primary provider with the local OpenCode gateway
    Wires Google AI Studio as primary provider (free 1500 req/day) with
    Vikey.ai as automatic fallback when primary quota is exhausted or fails.
    """
    from komdigi_bot.config import get_settings

    s = get_settings()
    client = LLMClient(
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        vision_model=s.llm_model_vision,
        reasoning_model=s.llm_model_reasoning,
    )
    # Wire Vikey.ai as fallback when configured
    if s.llm_fallback_base_url and s.llm_fallback_api_key:
        client._fallbacks = [(s.llm_fallback_base_url, s.llm_fallback_api_key)]
        logger.debug(
            "LLM fallback provider configured: %s",
            s.llm_fallback_base_url,
        )
    return client
