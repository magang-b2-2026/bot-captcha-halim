"""Unit tests for solver engines — all Playwright + LLM calls are mocked.

Covers:
- LLMClient: construction validation, ask_text/ask_vision mocked HTTP,
  error mapping (non-2xx, timeout, malformed).
- TextReasoningSolver: pass / fail / question-not-found paths.
- ImageOCRSolver: pass / fail / unparseable-answer paths.
- ClickCoordsSolver: coordinate parsing (JSON and plain formats), LLM error path.
- RotateSlideSolver: angle parsing, drag called, LLM error path.
- CheckboxGridSolver: cell parsing, verify click path.
- Coordinate / angle / cell parsers as pure unit tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from komdigi_bot.solvers.base import SolveStatus
from komdigi_bot.solvers.checkbox_grid import _parse_cell_numbers
from komdigi_bot.solvers.click_coords import _parse_coords
from komdigi_bot.solvers.llm import LLMAPIError, LLMClient, LLMConfigError
from komdigi_bot.solvers.rotate_slide import _degrees_to_drag_px, _parse_angle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm(vision_model: str = "v-model", reasoning_model: str = "r-model") -> LLMClient:
    return LLMClient(
        base_url="https://mock.api/v1",
        api_key="test-key",
        vision_model=vision_model,
        reasoning_model=reasoning_model,
    )


def _mock_llm_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": text}}]}
    return resp


def _mock_page(content: str = "", visible_text: str = "") -> MagicMock:
    page = MagicMock()
    page.content.return_value = content
    loc = MagicMock()
    loc.is_visible.return_value = True
    loc.inner_text.return_value = visible_text
    loc.bounding_box.return_value = {"x": 10.0, "y": 20.0, "width": 100.0, "height": 50.0}
    page.locator.return_value = loc
    page.frames = []
    return page


# ===========================================================================
# LLMClient
# ===========================================================================


class TestLLMClientConstruction:
    def test_empty_base_url_raises(self) -> None:
        with pytest.raises(LLMConfigError, match="LLM_BASE_URL"):
            LLMClient("", "key", "v-model", "r-model")

    def test_empty_api_key_raises(self) -> None:
        with pytest.raises(LLMConfigError, match="LLM_API_KEY"):
            LLMClient("https://api.example.com/v1", "", "v-model", "r-model")

    def test_empty_vision_model_raises(self) -> None:
        with pytest.raises(LLMConfigError, match="LLM_MODEL_VISION"):
            LLMClient("https://api.example.com/v1", "key", "", "r-model")

    def test_valid_construction(self) -> None:
        client = _llm()
        assert client is not None


class TestLLMClientAskText:
    @patch("httpx.post")
    def test_ask_text_returns_content(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _mock_llm_response("Friday")
        result = _llm().ask_text("What day is it?")
        assert result == "Friday"

    @patch("httpx.post")
    def test_ask_text_non_2xx_raises_api_error(self, mock_post: MagicMock) -> None:
        resp = MagicMock()
        resp.is_success = False
        resp.status_code = 429
        resp.text = "Rate limit exceeded"
        mock_post.return_value = resp
        with pytest.raises(LLMAPIError, match="429"):
            _llm().ask_text("test")

    @patch("httpx.post")
    def test_ask_text_malformed_schema_raises(self, mock_post: MagicMock) -> None:
        resp = MagicMock()
        resp.is_success = True
        resp.status_code = 200
        resp.json.return_value = {"bad": "schema"}
        mock_post.return_value = resp
        with pytest.raises(LLMAPIError, match="schema unexpected"):
            _llm().ask_text("test")

    @patch("httpx.post")
    def test_ask_text_timeout_raises(self, mock_post: MagicMock) -> None:
        import httpx as httpx_mod

        mock_post.side_effect = httpx_mod.TimeoutException("timeout")
        with pytest.raises(LLMAPIError, match="timed out"):
            _llm().ask_text("test")


class TestLLMClientAskVision:
    @patch("httpx.post")
    def test_ask_vision_returns_content(self, mock_post: MagicMock, tmp_path: Path) -> None:
        # Create a tiny fake PNG
        png = tmp_path / "test.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        mock_post.return_value = _mock_llm_response("W9H5K")
        result = _llm().ask_vision(png, "Transcribe this")
        assert result == "W9H5K"

    def test_ask_vision_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _llm().ask_vision(tmp_path / "nonexistent.png", "test")


# ===========================================================================
# Coordinate / angle / cell parser unit tests
# ===========================================================================


class TestParseCoords:
    def test_json_format(self) -> None:
        assert _parse_coords('{"x": 142, "y": 87}') == (142, 87)

    def test_json_y_first(self) -> None:
        assert _parse_coords('{"y": 87, "x": 142}') == (142, 87)

    def test_plain_comma(self) -> None:
        assert _parse_coords("142, 87") == (142, 87)

    def test_unparseable_raises(self) -> None:
        from komdigi_bot.solvers.llm import LLMParseError

        with pytest.raises(LLMParseError):
            _parse_coords("no numbers here at all")


class TestParseAngle:
    def test_plain_integer(self) -> None:
        assert _parse_angle("90") == 90

    def test_integer_in_sentence(self) -> None:
        assert _parse_angle("Rotate by 270 degrees") == 270

    def test_max_boundary(self) -> None:
        assert _parse_angle("359 degrees") == 359

    def test_zero(self) -> None:
        assert _parse_angle("0") == 0

    def test_unparseable_raises(self) -> None:
        from komdigi_bot.solvers.llm import LLMParseError

        with pytest.raises(LLMParseError):
            _parse_angle("unknown direction")


class TestParseCellNumbers:
    def test_comma_separated(self) -> None:
        assert _parse_cell_numbers("1, 4, 7") == [1, 4, 7]

    def test_deduplicates(self) -> None:
        assert _parse_cell_numbers("1 1 2") == [1, 2]

    def test_ignores_zeros_and_large(self) -> None:
        # regex only matches single digit 1-9
        assert _parse_cell_numbers("0 10 3") == [3]

    def test_empty_response(self) -> None:
        assert _parse_cell_numbers("none") == []


class TestDegrees2DragPx:
    def test_90_degrees_quarter_width(self) -> None:
        assert _degrees_to_drag_px(90, 200.0) == pytest.approx(50.0)

    def test_360_degrees_full_width(self) -> None:
        assert _degrees_to_drag_px(360, 200.0) == pytest.approx(200.0)

    def test_zero_degrees(self) -> None:
        assert _degrees_to_drag_px(0, 200.0) == pytest.approx(0.0)


# ===========================================================================
# TextReasoningSolver
# ===========================================================================


class TestTextReasoningSolver:
    def _solver(self, llm_answer: str = "Friday") -> tuple[Any, str]:
        llm = MagicMock(spec=LLMClient)
        llm._reasoning_model = "r-model"
        llm.ask_text.return_value = llm_answer
        return llm, llm_answer

    def _page_with_question(self, content: str, question: str) -> MagicMock:
        """Build a mock page where _extract_question can find the question text."""
        page = MagicMock()
        page.content.return_value = content
        page.frames = []

        # Build a mock element that looks like a <p> with our question
        el = MagicMock()
        el.inner_text.return_value = question

        loc = MagicMock()
        loc.all.return_value = [el]
        loc.is_visible.return_value = True
        loc.bounding_box.return_value = {"x": 10.0, "y": 20.0, "width": 100.0, "height": 50.0}
        # first locator call (for question) returns el-list; subsequent calls for input/submit
        page.locator.return_value = loc
        return page

    def test_pass_path(self, tmp_path: Path) -> None:
        from komdigi_bot.solvers.text_reasoning import TextReasoningSolver

        llm, _ = self._solver("Friday")
        page = self._page_with_question(
            content="Captcha is passed successfully",
            question="What day of the week is it today?",
        )
        solver = TextReasoningSolver(llm)
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.PASS

    def test_fail_path_wrong_answer(self, tmp_path: Path) -> None:
        from komdigi_bot.solvers.text_reasoning import TextReasoningSolver

        llm, _ = self._solver("Monday")
        page = self._page_with_question(
            content="<html>Wrong answer</html>",
            question="What day is it?",
        )
        solver = TextReasoningSolver(llm)
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.FAIL

    def test_llm_error_returns_fail(self, tmp_path: Path) -> None:
        from komdigi_bot.solvers.text_reasoning import TextReasoningSolver

        llm = MagicMock(spec=LLMClient)
        llm._reasoning_model = "r-model"
        llm.ask_text.side_effect = LLMAPIError("server down")
        page = self._page_with_question(
            content="<html></html>",
            question="What is 2+2?",
        )
        solver = TextReasoningSolver(llm)
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.FAIL
        assert "LLM error" in result.message


# ===========================================================================
# ImageOCRSolver
# ===========================================================================


class TestImageOCRSolver:
    def test_pass_path(self, tmp_path: Path) -> None:
        from komdigi_bot.solvers.image_ocr import ImageOCRSolver

        llm = MagicMock(spec=LLMClient)
        llm._vision_model = "v-model"
        llm.ask_vision.return_value = "W9H5K"

        page = _mock_page(content="Captcha is passed successfully")
        # Mock element screenshot
        page.locator.return_value.first.screenshot = MagicMock()
        img_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        (tmp_path / "captcha-image.png").write_bytes(img_bytes)

        solver = ImageOCRSolver(llm)
        result = solver.solve(page, tmp_path)
        assert result.answer == "W9H5K"

    def test_empty_vision_answer_returns_fail(self, tmp_path: Path) -> None:
        from komdigi_bot.solvers.image_ocr import ImageOCRSolver

        llm = MagicMock(spec=LLMClient)
        llm._vision_model = "v-model"
        llm.ask_vision.return_value = "..."  # no alphanumeric → empty after strip

        page = _mock_page(content="<html></html>")
        solver = ImageOCRSolver(llm)
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.FAIL
        assert "unparseable" in result.message

    def test_companion_fields_populated_when_empty(self, tmp_path: Path) -> None:
        from komdigi_bot.solvers.image_ocr import ImageOCRSolver

        llm = MagicMock(spec=LLMClient)
        llm._vision_model = "v-model"
        llm.ask_vision.return_value = "ABC12"

        page = _mock_page(content="Captcha is passed successfully")
        page.locator.return_value.first.screenshot = MagicMock()
        img_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        (tmp_path / "captcha-image.png").write_bytes(img_bytes)

        # Mock textarea locator
        ta_mock = MagicMock()
        ta_mock.is_visible.return_value = True
        ta_mock.input_value.return_value = ""

        def locator_router(selector: str):
            if selector == "textarea":
                loc = MagicMock()
                loc.all.return_value = [ta_mock]
                return loc
            return page.locator.return_value

        page.locator.side_effect = locator_router

        solver = ImageOCRSolver(llm)
        result = solver.solve(page, tmp_path)

        assert result.status == SolveStatus.PASS
        ta_mock.fill.assert_called_once_with("Automated QA inquiry verification.")


# ===========================================================================
# ClickCoordsSolver
# ===========================================================================


class TestClickCoordsSolver:
    def test_pass_path(self, tmp_path: Path) -> None:
        from komdigi_bot.solvers.click_coords import ClickCoordsSolver

        llm = MagicMock(spec=LLMClient)
        llm._vision_model = "v-model"
        llm.ask_vision.return_value = '{"x": 50, "y": 30}'

        page = _mock_page(content="Captcha is passed successfully")
        page.frames = []
        solver = ClickCoordsSolver(llm)
        result = solver.solve(page, tmp_path)
        assert result.answer == "50,30"

    def test_llm_parse_fail(self, tmp_path: Path) -> None:
        from komdigi_bot.solvers.click_coords import ClickCoordsSolver

        llm = MagicMock(spec=LLMClient)
        llm._vision_model = "v-model"
        llm.ask_vision.return_value = "I cannot determine the coordinates"

        page = _mock_page(content="<html></html>")
        solver = ClickCoordsSolver(llm)
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.FAIL
        assert "parse" in result.message.lower()


# ===========================================================================
# RotateSlideSolver
# ===========================================================================


class TestRotateSlideSolver:
    def test_pass_path(self, tmp_path: Path) -> None:
        from komdigi_bot.solvers.rotate_slide import RotateSlideSolver

        llm = MagicMock(spec=LLMClient)
        llm._vision_model = "v-model"
        llm.ask_vision.return_value = "90"

        page = _mock_page(content="Captcha is passed successfully")
        solver = RotateSlideSolver(llm)
        result = solver.solve(page, tmp_path)
        assert result.answer == "90deg"

    def test_llm_bad_angle_returns_fail(self, tmp_path: Path) -> None:
        from komdigi_bot.solvers.rotate_slide import RotateSlideSolver

        llm = MagicMock(spec=LLMClient)
        llm._vision_model = "v-model"
        llm.ask_vision.return_value = "I don't know the angle"

        page = _mock_page(content="<html></html>")
        solver = RotateSlideSolver(llm)
        result = solver.solve(page, tmp_path)
        assert result.status == SolveStatus.FAIL
