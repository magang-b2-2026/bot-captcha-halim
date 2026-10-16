"""Tests for 2captcha client and API fallback solver — all HTTP calls mocked."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from komdigi_bot.solvers.base import SolveStatus
from komdigi_bot.solvers.fallback.twocaptcha import (
    TwoCaptchaClient,
    TwoCaptchaError,
    TwoCaptchaTimeout,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client(key: str = "test-key") -> TwoCaptchaClient:
    return TwoCaptchaClient(api_key=key, poll_interval=0.01, max_wait=0.5)


def _resp(body: dict[str, Any], status: int = 200) -> MagicMock:
    r = MagicMock()
    r.is_success = 200 <= status < 300
    r.status_code = status
    r.json.return_value = body
    r.text = json.dumps(body)
    return r


def _create_ok(task_id: int = 42) -> dict[str, Any]:
    return {"taskId": task_id}


def _result_processing() -> dict[str, Any]:
    return {"status": "processing"}


def _result_ready(solution: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ready", "solution": solution}


# ===========================================================================
# TwoCaptchaClient — construction
# ===========================================================================


class TestTwoCaptchaConstruction:
    def test_empty_key_raises(self) -> None:
        with pytest.raises(TwoCaptchaError, match="TWOCAPTCHA_API_KEY"):
            TwoCaptchaClient(api_key="")

    def test_valid_construction(self) -> None:
        assert _client() is not None


# ===========================================================================
# TwoCaptchaClient — submit + poll
# ===========================================================================


class TestTwoCaptchaSubmitAndPoll:
    @patch("httpx.post")
    def test_turnstile_happy_path(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = [
            _resp(_create_ok(99)),
            _resp(_result_ready({"token": "cf-token-xyz"})),
        ]
        result = _client().solve_turnstile("https://example.com", "0x1234")
        assert result == "cf-token-xyz"

    @patch("httpx.post")
    def test_polls_until_ready(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = [
            _resp(_create_ok(77)),
            _resp(_result_processing()),
            _resp(_result_processing()),
            _resp(_result_ready({"token": "t1"})),
        ]
        result = _client().solve_turnstile("https://example.com", "0xABC")
        assert result == "t1"
        assert mock_post.call_count == 4

    @patch("httpx.post")
    def test_timeout_raises(self, mock_post: MagicMock) -> None:
        import itertools

        # Provide create OK then unlimited processing responses
        mock_post.side_effect = itertools.chain(
            [_resp(_create_ok(1))],
            itertools.repeat(_resp(_result_processing())),
        )
        with pytest.raises(TwoCaptchaTimeout):
            _client().solve_turnstile("https://example.com", "0xXXX")

    @patch("httpx.post")
    def test_error_code_raises(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _resp(
            {"errorCode": "ERROR_KEY_DOES_NOT_EXIST", "errorDescription": "Bad key"}
        )
        with pytest.raises(TwoCaptchaError, match="ERROR_KEY_DOES_NOT_EXIST"):
            _client().solve_turnstile("https://example.com", "0xBAD")

    @patch("httpx.post")
    def test_http_5xx_raises(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _resp({}, 503)
        with pytest.raises(TwoCaptchaError, match="503"):
            _client().solve_turnstile("https://example.com", "0xBAD")

    @patch("httpx.post")
    def test_funcaptcha_returns_token(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = [
            _resp(_create_ok(5)),
            _resp(_result_ready({"token": "arkose-tok"})),
        ]
        result = _client().solve_funcaptcha("https://example.com", "pub-key-abc")
        assert result == "arkose-tok"

    @patch("httpx.post")
    def test_geetest_returns_solution_dict(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = [
            _resp(_create_ok(6)),
            _resp(
                _result_ready(
                    {
                        "validate": "abc123",
                        "seccode": "abc123|jordan",
                        "challenge": "ch_xyz",
                    }
                )
            ),
        ]
        result = _client().solve_geetest("https://example.com", "gt_abc", "ch_xyz")
        assert result["geetest_validate"] == "abc123"
        assert "geetest_seccode" in result

    @patch("httpx.post")
    def test_recaptcha_v2_returns_token(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = [
            _resp(_create_ok(7)),
            _resp(_result_ready({"gRecaptchaResponse": "03AGdBq25..."})),
        ]
        result = _client().solve_recaptcha_v2("https://example.com", "6Le...")
        assert result.startswith("03AGdBq25")


# ===========================================================================
# APIFallbackSolver
# ===========================================================================


class TestAPIFallbackSolver:
    def _make(self, family: str = "turnstile", site_key: str = "0x1234") -> Any:
        from komdigi_bot.solvers.fallback.api_solver import APIFallbackSolver

        client = MagicMock(spec=TwoCaptchaClient)
        client.solve_turnstile.return_value = "cf-tok"
        client.solve_funcaptcha.return_value = "arkose-tok"
        client.solve_recaptcha_v2.return_value = "recaptcha-tok"
        client.solve_geetest.return_value = {
            "geetest_validate": "val",
            "geetest_seccode": "sec",
            "geetest_challenge": "ch",
        }

        return APIFallbackSolver(
            client=client,
            family=family,
            site_key=site_key,
            page_url="https://2captcha.com/demo/turnstile",
        ), client

    def _mock_page(self, passed: bool = True) -> MagicMock:
        page = MagicMock()
        page.content.return_value = "Captcha is passed successfully" if passed else "<html></html>"
        page.url = "https://2captcha.com/demo/turnstile"
        loc = MagicMock()
        loc.is_visible.return_value = True
        page.locator.return_value = loc
        return page

    def test_turnstile_pass(self, tmp_path):  # type: ignore[no-untyped-def]

        solver, client = self._make("turnstile")
        page = self._mock_page(passed=True)
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.PASS
        client.solve_turnstile.assert_called_once()

    def test_arkose_pass(self, tmp_path):  # type: ignore[no-untyped-def]
        solver, client = self._make("arkose")
        page = self._mock_page(passed=True)
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.PASS
        client.solve_funcaptcha.assert_called_once()

    def test_twocaptcha_error_returns_fail(self, tmp_path):  # type: ignore[no-untyped-def]
        solver, client = self._make("turnstile")
        client.solve_turnstile.side_effect = TwoCaptchaError("bad key")
        page = self._mock_page()
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.FAIL
        assert "2captcha error" in result.message

    def test_timeout_returns_fail(self, tmp_path):  # type: ignore[no-untyped-def]
        solver, client = self._make("turnstile")
        client.solve_turnstile.side_effect = TwoCaptchaTimeout("120s elapsed")
        page = self._mock_page()
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.FAIL
        assert "timeout" in result.message.lower()

    def test_unsupported_family_returns_skip(self, tmp_path):  # type: ignore[no-untyped-def]
        solver, _ = self._make("unknown_family")
        page = self._mock_page()
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.SKIP


# ===========================================================================
# Site key extraction
# ===========================================================================


class TestExtractSiteKey:
    def test_turnstile_data_sitekey(self) -> None:
        from komdigi_bot.solvers.fallback.api_solver import _extract_site_key

        page = MagicMock()
        page.content.return_value = '<div class="cf-turnstile" data-sitekey="0x4AAAA123"></div>'
        assert _extract_site_key(page, "turnstile") == "0x4AAAA123"

    def test_recaptcha_sitekey(self) -> None:
        from komdigi_bot.solvers.fallback.api_solver import _extract_site_key

        page = MagicMock()
        page.content.return_value = '<div class="g-recaptcha" data-sitekey="6Le1234xyz"></div>'
        assert _extract_site_key(page, "recaptcha") == "6Le1234xyz"

    def test_missing_key_returns_empty(self) -> None:
        from komdigi_bot.solvers.fallback.api_solver import _extract_site_key

        page = MagicMock()
        page.content.return_value = "<html><body>No captcha here</body></html>"
        assert _extract_site_key(page, "turnstile") == ""
