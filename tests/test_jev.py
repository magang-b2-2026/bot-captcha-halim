"""Tests for komdigi_bot.decision.jev — all HTTP calls are mocked.

Covers:
- JevClient construction: empty key raises JevAuthError.
- ask(): choice/score/noul parsing from mocked responses.
- ask(): 401 → JevAuthError (clear message about console.typesafe.ai).
- ask(): 502 → JevServerError.
- ask(): malformed JSON → JevResponseError.
- ask(): missing "model" key → JevResponseError.
- Convenience shortcuts: client.noul(), client.choice(), client.score().
- JevAnswerNoul.is_true threshold (>0.5 = True).
- JevQuestion type validator rejects unknown type strings.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from komdigi_bot.decision.jev import (
    JevAnswerNoul,
    JevAuthError,
    JevClient,
    JevQuestion,
    JevRequest,
    JevResponseError,
    JevServerError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, body: Any = None, text: str = "") -> MagicMock:
    """Build a fake httpx.Response-like mock."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    if body is not None:
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = json.JSONDecodeError("bad", "", 0)
        resp.text = text
    return resp


def _make_client(api_key: str = "test-key-abc") -> JevClient:
    return JevClient(api_key=api_key, endpoint="https://mock.api/v1/systemone", timeout=5.0)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestJevClientConstruction:
    def test_empty_key_raises_auth_error(self) -> None:
        with pytest.raises(JevAuthError, match="TYPESAFE_API_KEY"):
            JevClient(api_key="")

    def test_valid_key_creates_client(self) -> None:
        client = _make_client()
        assert client is not None


# ---------------------------------------------------------------------------
# ask() — response parsing
# ---------------------------------------------------------------------------


NOUL_BODY = {
    "model": "jev-1.2",
    "answers": {"q": {"noul": 0.93}},
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}

CHOICE_BODY = {
    "model": "jev-1.2",
    "answers": {"fam": {"choice": "recaptcha", "probability": 0.88}},
    "usage": {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23},
}

SCORE_BODY = {
    "model": "jev-1.2",
    "answers": {"conf": {"score": 0.72, "confidence": 0.9}},
    "usage": {"prompt_tokens": 15, "completion_tokens": 4, "total_tokens": 19},
}


class TestJevClientParsing:
    def _req_noul(self) -> JevRequest:
        return JevRequest(
            model="jev-latest",
            state="test state",
            questions={"q": JevQuestion(type="noul", instructions="True?")},
        )

    def _req_choice(self) -> JevRequest:
        return JevRequest(
            model="jev-latest",
            state="page html",
            questions={
                "fam": JevQuestion(
                    type="choice",
                    instructions="Which captcha?",
                    criteria={"recaptcha": "reCAPTCHA detected", "turnstile": "Turnstile detected"},
                )
            },
        )

    def _req_score(self) -> JevRequest:
        return JevRequest(
            model="jev-latest",
            state="answer",
            questions={"conf": JevQuestion(type="score", instructions="Confidence?")},
        )

    @patch("httpx.post")
    def test_noul_parsed_correctly(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, NOUL_BODY)
        resp = _make_client().ask(self._req_noul())
        noul = resp.noul("q")
        assert noul.noul == pytest.approx(0.93)
        assert noul.is_true is True

    @patch("httpx.post")
    def test_choice_parsed_correctly(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, CHOICE_BODY)
        resp = _make_client().ask(self._req_choice())
        choice = resp.choice("fam")
        assert choice.choice == "recaptcha"
        assert choice.probability == pytest.approx(0.88)

    @patch("httpx.post")
    def test_score_parsed_correctly(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, SCORE_BODY)
        resp = _make_client().ask(self._req_score())
        score = resp.score("conf")
        assert score.score == pytest.approx(0.72)

    @patch("httpx.post")
    def test_usage_parsed(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, NOUL_BODY)
        resp = _make_client().ask(self._req_noul())
        assert resp.usage.total_tokens == 15
        assert resp.model == "jev-1.2"


# ---------------------------------------------------------------------------
# ask() — error handling
# ---------------------------------------------------------------------------


class TestJevClientErrors:
    def _noul_req(self) -> JevRequest:
        return JevRequest(
            state="x",
            questions={"q": JevQuestion(type="noul", instructions="ok?")},
        )

    @patch("httpx.post")
    def test_401_raises_auth_error_with_hint(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(401, text="Unauthorized")
        with pytest.raises(JevAuthError, match="console.typesafe.ai"):
            _make_client().ask(self._noul_req())

    @patch("httpx.post")
    def test_502_raises_server_error(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(502, text="Bad Gateway")
        with pytest.raises(JevServerError):
            _make_client().ask(self._noul_req())

    @patch("httpx.post")
    def test_503_raises_server_error(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(503, text="Service Unavailable")
        with pytest.raises(JevServerError):
            _make_client().ask(self._noul_req())

    @patch("httpx.post")
    def test_malformed_json_raises_response_error(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, text="not json at all")
        with pytest.raises(JevResponseError, match="not valid JSON"):
            _make_client().ask(self._noul_req())

    @patch("httpx.post")
    def test_missing_model_key_raises_response_error(self, mock_post: MagicMock) -> None:
        bad_body = {"answers": {"q": {"noul": 0.5}}, "usage": {}}  # missing "model"
        mock_post.return_value = _mock_response(200, bad_body)
        with pytest.raises(JevResponseError, match="schema mismatch"):
            _make_client().ask(self._noul_req())


# ---------------------------------------------------------------------------
# Convenience shortcuts
# ---------------------------------------------------------------------------


class TestJevClientShortcuts:
    @patch("httpx.post")
    def test_noul_shortcut(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, NOUL_BODY)
        result = _make_client().noul("test state", "q", "True?")
        assert isinstance(result, JevAnswerNoul)
        assert result.noul == pytest.approx(0.93)

    @patch("httpx.post")
    def test_choice_shortcut(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, CHOICE_BODY)
        result = _make_client().choice(
            "page html",
            "fam",
            "Which captcha?",
            {"recaptcha": "reCAPTCHA", "turnstile": "Turnstile"},
        )
        assert result.choice == "recaptcha"

    @patch("httpx.post")
    def test_score_shortcut(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_response(200, SCORE_BODY)
        result = _make_client().score("answer", "conf", "Confidence?")
        assert result.score == pytest.approx(0.72)


# ---------------------------------------------------------------------------
# Model / data validation
# ---------------------------------------------------------------------------


class TestJevModels:
    def test_noul_is_true_above_threshold(self) -> None:
        assert JevAnswerNoul(noul=0.51).is_true is True

    def test_noul_is_false_at_threshold(self) -> None:
        assert JevAnswerNoul(noul=0.5).is_true is False

    def test_noul_is_false_below_threshold(self) -> None:
        assert JevAnswerNoul(noul=0.0).is_true is False

    def test_invalid_question_type_raises(self) -> None:
        with pytest.raises(ValueError, match="must be one of"):
            JevQuestion(type="unknown", instructions="test")
