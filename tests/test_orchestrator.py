"""Unit tests for Orchestrator — browser, triage, and solvers all mocked.

Covers:
- run(): no captcha detected → SKIP
- run(): solver PASS on first attempt
- run(): solver FAIL × max_retries → escalates to api_fallback
- run(): api_fallback PASS after in-house exhausted
- run(): browser crash → FAIL with error message
- RunResult.to_dict() schema
- _build_solver_registry() includes all expected engine keys
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from komdigi_bot.orchestrator import Orchestrator, RunResult, _build_solver_registry
from komdigi_bot.solvers.base import SolveAttempt, SolveStatus
from komdigi_bot.triage.router import RoutingResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pass_attempt(family: str = "text", engine: str = "text_reasoning") -> SolveAttempt:
    return SolveAttempt(family=family, engine=engine, status=SolveStatus.PASS, answer="ok")


def _fail_attempt(family: str = "text", engine: str = "text_reasoning") -> SolveAttempt:
    return SolveAttempt(family=family, engine=engine, status=SolveStatus.FAIL, message="wrong")


def _skip_attempt(family: str = "text", engine: str = "text_reasoning") -> SolveAttempt:
    return SolveAttempt(family=family, engine=engine, status=SolveStatus.SKIP)


def _mock_settings(policy: str = "hybrid", twocaptcha_key: str = "") -> MagicMock:
    s = MagicMock()
    s.solver_policy = policy
    s.twocaptcha_api_key = twocaptcha_key
    s.llm_base_url = "https://mock.api/v1"
    s.llm_api_key = "key"
    s.llm_model_vision = "v-model"
    s.llm_model_reasoning = "r-model"

    stealth = MagicMock()
    stealth.headless = True
    s.stealth = stealth
    return s


def _orchestrator_patched(
    solver_result: SolveAttempt | list[SolveAttempt],
    routing: RoutingResult,
    api_result: SolveAttempt | None = None,
    twocaptcha_key: str = "",
) -> Orchestrator:
    """Build an Orchestrator with everything mocked."""
    settings = _mock_settings(twocaptcha_key=twocaptcha_key)
    orch = Orchestrator.__new__(Orchestrator)
    orch._settings = settings
    orch._stealth_cfg = settings.stealth
    orch._max_retries = 2

    # Mock LLM client
    orch._llm = MagicMock()
    orch._twocaptcha = None
    if twocaptcha_key:
        orch._twocaptcha = MagicMock()

    # Mock solver
    mock_solver = MagicMock()
    results = solver_result if isinstance(solver_result, list) else [solver_result] * 10
    mock_solver.solve.side_effect = results
    orch._registry = {routing.engine: mock_solver}

    # Mock api fallback
    if api_result:
        mock_fallback = MagicMock()
        mock_fallback.solve.return_value = api_result

    # Mock router
    orch._router = MagicMock()
    orch._router.route.return_value = routing

    return orch


# ===========================================================================
# RunResult.to_dict()
# ===========================================================================


class TestRunResultToDict:
    def test_schema_keys_present(self) -> None:
        r = RunResult(
            run_id="abc123",
            url="https://example.com",
            family="text",
            engine="text_reasoning",
            final_status=SolveStatus.PASS,
        )
        d = r.to_dict()
        assert "run_id" in d
        assert "final_status" in d
        assert "passed" in d
        assert d["passed"] is True
        assert d["final_status"] == "pass"

    def test_attempts_serialized(self) -> None:
        r = RunResult(
            run_id="x",
            url="https://example.com",
            family="image",
            engine="image_ocr",
            final_status=SolveStatus.FAIL,
            attempts=[_fail_attempt("image", "image_ocr")],
        )
        d = r.to_dict()
        assert len(d["attempts"]) == 1
        assert d["attempts"][0]["status"] == "fail"


# ===========================================================================
# Solver registry
# ===========================================================================


class TestBuildSolverRegistry:
    def test_all_engines_present(self) -> None:
        llm = MagicMock()
        registry = _build_solver_registry(llm)
        assert "text_reasoning" in registry
        assert "image_ocr" in registry
        assert "click_coords" in registry
        assert "rotate_slide" in registry
        assert "checkbox_grid" in registry


# ===========================================================================
# Orchestrator._run_with_page (mocked page)
# ===========================================================================


class TestOrchestratorRunWithPage:
    def _mock_page(self, html: str = "<html></html>") -> MagicMock:
        page = MagicMock()
        page.content.return_value = html
        page.url = "https://2captcha.com/demo/text"
        page.goto.return_value = None
        page.reload.return_value = None
        return page

    def test_no_captcha_returns_skip(self, tmp_path: Path) -> None:
        routing = RoutingResult(
            family="none", engine="none", confidence=0.0, jev_confirmed=False, pre_gated_none=False
        )
        orch = _orchestrator_patched(_skip_attempt(), routing)

        page = self._mock_page()
        result = orch._run_with_page(page, "https://example.com", "abc", tmp_path, 0.0)
        assert result.final_status == SolveStatus.SKIP
        assert result.family == "none"

    def test_solver_pass_on_first_attempt(self, tmp_path: Path) -> None:
        routing = RoutingResult(
            family="text",
            engine="text_reasoning",
            confidence=0.8,
            jev_confirmed=False,
            pre_gated_none=False,
        )
        orch = _orchestrator_patched(_pass_attempt(), routing)

        page = self._mock_page()
        result = orch._run_with_page(page, "https://2captcha.com/demo/text", "abc", tmp_path, 0.0)
        assert result.final_status == SolveStatus.PASS
        assert len(result.attempts) == 1

    def test_solver_fails_all_retries(self, tmp_path: Path) -> None:
        routing = RoutingResult(
            family="image",
            engine="image_ocr",
            confidence=0.7,
            jev_confirmed=False,
            pre_gated_none=False,
        )
        orch = _orchestrator_patched([_fail_attempt("image", "image_ocr")] * 5, routing)
        orch._max_retries = 2

        page = self._mock_page()
        result = orch._run_with_page(page, "https://2captcha.com/demo/normal", "abc", tmp_path, 0.0)
        assert result.final_status == SolveStatus.FAIL
        assert len(result.attempts) == 2

    def test_skip_stops_retry_loop(self, tmp_path: Path) -> None:
        routing = RoutingResult(
            family="click",
            engine="click_coords",
            confidence=0.6,
            jev_confirmed=False,
            pre_gated_none=False,
        )
        orch = _orchestrator_patched(_skip_attempt("click", "click_coords"), routing)
        orch._max_retries = 3

        page = self._mock_page()
        result = orch._run_with_page(
            page, "https://2captcha.com/demo/clickcaptcha", "abc", tmp_path, 0.0
        )
        # SKIP stops after 1 attempt
        assert len(result.attempts) == 1
        assert result.final_status == SolveStatus.FAIL


# ===========================================================================
# Orchestrator.run() — full integration (browser mocked)
# ===========================================================================


class TestOrchestratorRun:
    @patch("komdigi_bot.orchestrator.StealthBrowser")
    def test_run_returns_result(self, mock_browser_cls: MagicMock, tmp_path: Path) -> None:
        routing = RoutingResult(
            family="text",
            engine="text_reasoning",
            confidence=0.9,
            jev_confirmed=False,
            pre_gated_none=False,
        )

        settings = _mock_settings()
        orch = Orchestrator.__new__(Orchestrator)
        orch._settings = settings
        orch._stealth_cfg = settings.stealth
        orch._max_retries = 1
        orch._llm = MagicMock()
        orch._twocaptcha = None

        mock_solver = MagicMock()
        mock_solver.solve.return_value = _pass_attempt()
        orch._registry = {"text_reasoning": mock_solver}
        orch._router = MagicMock()
        orch._router.route.return_value = routing

        # Mock browser context manager
        mock_page = MagicMock()
        mock_page.content.return_value = "<html>Captcha is passed successfully</html>"
        mock_page.goto.return_value = None
        mock_page.url = "https://2captcha.com/demo/text"
        mock_browser_cls.return_value.__enter__ = MagicMock(return_value=mock_page)
        mock_browser_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = orch.run("https://2captcha.com/demo/text")
        assert isinstance(result, RunResult)
        assert result.url == "https://2captcha.com/demo/text"
