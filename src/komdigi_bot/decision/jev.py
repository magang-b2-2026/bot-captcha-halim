"""TypeSafe AI System One (Jev) HTTP client.

Implements the ``POST /v1/systemone`` endpoint with typed request/response
models for the three question types:

* ``choice``  — classify state into one of N labelled options
* ``score``   — produce a float in [0, 1] with optional threshold gate
* ``noul``    — binary true/false inference

API contract (from jevtypesafeai.com/how-to-use + docs):
    POST https://api.typesafe.ai/v1/systemone
    Authorization: Bearer <TYPESAFE_API_KEY>
    {
        "model": "jev-latest",
        "state": <string | list | object>,
        "questions": {
            "<name>": {
                "type": "choice" | "score" | "noul",
                "instructions": <string>,
                "criteria": {<label>: <string>}  # choice only
            }
        }
    }

Response:
    {
        "model": <string>,
        "answers": {
            "<name>": {
                "choice": <string>,          # choice
                "probability": <float>,
                "score": <float>,            # score
                "confidence": <float>,
                "noul": <float>,             # noul  (0.0–1.0, threshold 0.5)
            }
        },
        "usage": {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
    }

Design decisions:
* Never silently returns a confident default on API errors — always raises.
* 401 → clear message pointing to console.typesafe.ai.
* 502/503/timeout → structured retry signal (callers handle backoff).
* State capped at 64 k tokens per API limits; no enforcement here — callers
  are responsible for passing reasonable state sizes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_API_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class JevQuestion(BaseModel):
    """A single question sent to Jev SystemOne."""

    type: str  # "choice" | "score" | "noul"
    instructions: str
    criteria: dict[str, str] | None = None  # required for type="choice"

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        allowed = {"choice", "score", "noul"}
        if v not in allowed:
            msg = f"Jev question type must be one of {allowed!r}, got {v!r}"
            raise ValueError(msg)
        return v


class JevRequest(BaseModel):
    """Payload sent to POST /v1/systemone."""

    model: str = "jev-latest"
    state: Any  # str | list[Any] | dict[str, Any]
    questions: dict[str, JevQuestion]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class JevAnswerChoice(BaseModel):
    """Answer for a ``choice`` question."""

    choice: str
    probability: float | None = None


class JevAnswerScore(BaseModel):
    """Answer for a ``score`` question."""

    score: float
    confidence: float | None = None


class JevAnswerNoul(BaseModel):
    """Answer for a ``noul`` question."""

    noul: float  # 0.0–1.0; > 0.5 ≈ True

    @property
    def is_true(self) -> bool:
        return self.noul > 0.5


class JevUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class JevResponse(BaseModel):
    """Full parsed response from SystemOne."""

    model: str
    answers: dict[str, dict[str, Any]]
    usage: JevUsage = JevUsage()

    def choice(self, name: str) -> JevAnswerChoice:
        return JevAnswerChoice(**self.answers[name])

    def score(self, name: str) -> JevAnswerScore:
        return JevAnswerScore(**self.answers[name])

    def noul(self, name: str) -> JevAnswerNoul:
        return JevAnswerNoul(**self.answers[name])


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class JevAuthError(RuntimeError):
    """Raised when the API returns 401 — key missing or invalid."""


class JevServerError(RuntimeError):
    """Raised on 5xx responses — signals transient failure, callers may retry."""


class JevResponseError(RuntimeError):
    """Raised when the response body cannot be parsed as expected."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class JevClient:
    """Thin synchronous HTTPX client for Jev SystemOne.

    Args:
        api_key: Value of ``TYPESAFE_API_KEY`` (never empty in production;
            pass empty string only in mocked tests).
        endpoint: Override the default ``api.typesafe.ai`` endpoint.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str = _API_ENDPOINT,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            msg = (
                "TYPESAFE_API_KEY is empty — obtain one from console.typesafe.ai "
                "and set it in your .env file."
            )
            raise JevAuthError(msg)
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout = timeout

    def ask(self, request: JevRequest) -> JevResponse:
        """Send *request* to Jev SystemOne and return a parsed :class:`JevResponse`.

        Raises:
            JevAuthError: API returned 401.
            JevServerError: API returned 5xx.
            JevResponseError: Response body is malformed.
            httpx.TimeoutException: Request timed out.
        """
        payload = request.model_dump(exclude_none=True)
        logger.debug("Jev request: model=%s questions=%s", request.model, list(request.questions))

        try:
            resp = httpx.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(payload),
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            logger.warning("Jev request timed out after %.1f s", self._timeout)
            raise

        if resp.status_code == 401:
            msg = (
                "Jev API returned 401 Unauthorized — check that TYPESAFE_API_KEY "
                "is a valid key from console.typesafe.ai."
            )
            raise JevAuthError(msg)

        if resp.status_code >= 500:
            msg = f"Jev API server error {resp.status_code}: {resp.text[:200]}"
            logger.warning(msg)
            raise JevServerError(msg)

        if not resp.is_success:
            msg = f"Jev API unexpected status {resp.status_code}: {resp.text[:200]}"
            raise JevResponseError(msg)

        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            msg = f"Jev response body is not valid JSON: {exc}"
            raise JevResponseError(msg) from exc

        try:
            usage_raw: dict[str, Any] = body.get("usage", {})
            return JevResponse(
                model=body["model"],
                answers=body["answers"],
                usage=JevUsage(**usage_raw) if usage_raw else JevUsage(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            msg = f"Jev response schema mismatch: {exc} — raw={body!r:.200}"
            raise JevResponseError(msg) from exc

    # ------------------------------------------------------------------
    # Convenience shortcuts
    # ------------------------------------------------------------------

    def choice(
        self,
        state: Any,
        name: str,
        instructions: str,
        criteria: dict[str, str],
        model: str = "jev-latest",
    ) -> JevAnswerChoice:
        """Single-question shortcut for a ``choice`` query."""
        req = JevRequest(
            model=model,
            state=state,
            questions={name: JevQuestion(type="choice", instructions=instructions, criteria=criteria)},
        )
        return self.ask(req).choice(name)

    def score(
        self,
        state: Any,
        name: str,
        instructions: str,
        model: str = "jev-latest",
    ) -> JevAnswerScore:
        """Single-question shortcut for a ``score`` query."""
        req = JevRequest(
            model=model,
            state=state,
            questions={name: JevQuestion(type="score", instructions=instructions)},
        )
        return self.ask(req).score(name)

    def noul(
        self,
        state: Any,
        name: str,
        instructions: str,
        model: str = "jev-latest",
    ) -> JevAnswerNoul:
        """Single-question shortcut for a ``noul`` query."""
        req = JevRequest(
            model=model,
            state=state,
            questions={name: JevQuestion(type="noul", instructions=instructions)},
        )
        return self.ask(req).noul(name)
