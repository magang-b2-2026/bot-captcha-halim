"""Tests for komdigi_bot.triage — detector and router.

12 fixture HTML snippets (one per family + "none") + router tests
with mocked Jev client.

Unit tests only — no browser, no network.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from komdigi_bot.decision.jev import JevAnswerChoice, JevAnswerNoul, JevResponseError
from komdigi_bot.triage.detector import CaptchaDetector
from komdigi_bot.triage.router import CaptchaRouter

# ---------------------------------------------------------------------------
# HTML fixtures per captcha family
# ---------------------------------------------------------------------------

FIXTURES: dict[str, str] = {
    "turnstile": """
        <div class="cf-turnstile" data-sitekey="0x4AAA..."></div>
        <script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>
        <script>window.turnstile = {};</script>
    """,
    "recaptcha": """
        <script src="https://www.google.com/recaptcha/api.js"></script>
        <div class="g-recaptcha" data-sitekey="6Le..."></div>
        <script>grecaptcha.ready(function() {});</script>
    """,
    "hcaptcha": """
        <script src="https://js.hcaptcha.com/1/api.js"></script>
        <div class="h-captcha" data-hcaptcha-sitekey="..."></div>
    """,
    "arkose": """
        <script src="https://client-api.arkoselabs.com/v2/api.js"></script>
        <div id="funcaptcha-container"></div>
    """,
    "geetest": """
        <script src="https://static.geetest.com/v4/gt4.js"></script>
        <div id="gt-captcha"></div>
        <script>initGeetest4({captchaId: '...'}, function(c) {});</script>
    """,
    "image": """
        <form>
          <img src="/captcha.png" alt="normal captcha example" />
          <input type="text" placeholder="Enter answer here..." name="captchaCode" />
        </form>
    """,
    "rotate": """
        <div class="rotatecaptcha">
          <img id="rotate-img" src="/puzzle.png" />
          <input type="range" class="rotate-slider" />
        </div>
    """,
    "click": """
        <div class="clickcaptcha">
          <canvas id="captcha-canvas"></canvas>
          <p>Click on the correct location</p>
        </div>
    """,
    "text": """
        <div class="text-captcha">
          <p>What day of the week is it today?</p>
          <input type="text" placeholder="Type your answer" />
        </div>
    """,
    # Fixture with multiple families to verify priority (turnstile wins)
    "mixed_turnstile_recaptcha": """
        <script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>
        <script src="https://www.google.com/recaptcha/api.js"></script>
    """,
    # Two non-overlapping but both detectable
    "recaptcha_enterprise": """
        <script src="https://www.google.com/recaptcha/enterprise.js"></script>
        <div class="g-recaptcha" data-sitekey="6Le..."></div>
    """,
    # Clean page, no captcha
    "none": """
        <html><body><h1>Welcome</h1><p>No captcha here.</p></body></html>
    """,
}


# ===========================================================================
# CaptchaDetector tests
# ===========================================================================


class TestCaptchaDetectorFamilies:
    """Each fixture must be detected as the correct family."""

    def _check(self, fixture_key: str, expected_family: str) -> None:
        html = FIXTURES[fixture_key]
        result = CaptchaDetector().detect(html)
        assert result.family == expected_family, (
            f"fixture={fixture_key!r}: expected family={expected_family!r}, "
            f"got={result.family!r} (confidence={result.confidence:.2f}, "
            f"sigs={result.matched_signatures})"
        )

    def test_turnstile(self) -> None:
        self._check("turnstile", "turnstile")

    def test_recaptcha(self) -> None:
        self._check("recaptcha", "recaptcha")

    def test_hcaptcha(self) -> None:
        self._check("hcaptcha", "hcaptcha")

    def test_arkose(self) -> None:
        self._check("arkose", "arkose")

    def test_geetest(self) -> None:
        self._check("geetest", "geetest")

    def test_image(self) -> None:
        self._check("image", "image")

    def test_rotate(self) -> None:
        self._check("rotate", "rotate")

    def test_click(self) -> None:
        self._check("click", "click")

    def test_text(self) -> None:
        self._check("text", "text")

    def test_none_returns_none_family(self) -> None:
        self._check("none", "none")

    def test_mixed_turnstile_wins(self) -> None:
        """When multiple families match, priority order determines winner."""
        result = CaptchaDetector().detect(FIXTURES["mixed_turnstile_recaptcha"])
        assert result.family == "turnstile"

    def test_recaptcha_enterprise_detected(self) -> None:
        result = CaptchaDetector().detect(FIXTURES["recaptcha_enterprise"])
        assert result.family == "recaptcha"


class TestCaptchaDetectorConfidence:
    def test_strong_match_high_confidence(self) -> None:
        result = CaptchaDetector().detect(FIXTURES["turnstile"])
        assert result.confidence >= 0.5

    def test_none_page_confidence_zero(self) -> None:
        result = CaptchaDetector().detect(FIXTURES["none"])
        assert result.confidence == 0.0

    def test_detected_flag(self) -> None:
        assert CaptchaDetector().detect(FIXTURES["recaptcha"]).detected is True
        assert CaptchaDetector().detect(FIXTURES["none"]).detected is False

    def test_matched_signatures_not_empty_on_match(self) -> None:
        result = CaptchaDetector().detect(FIXTURES["geetest"])
        assert len(result.matched_signatures) >= 1


class TestCaptchaDetectorDetectAll:
    def test_detect_all_returns_sorted_list(self) -> None:
        # Mixed page has both turnstile and recaptcha
        results = CaptchaDetector().detect_all(FIXTURES["mixed_turnstile_recaptcha"])
        assert len(results) >= 2
        confidences = [r.confidence for r in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_detect_all_empty_on_clean_page(self) -> None:
        results = CaptchaDetector().detect_all(FIXTURES["none"])
        assert results == []


# ===========================================================================
# CaptchaRouter tests (Jev mocked)
# ===========================================================================


def _jev_none_negative() -> MagicMock:
    """Jev noul says there IS a captcha (noul < threshold)."""
    mock = MagicMock()
    mock.noul.return_value = JevAnswerNoul(noul=0.1)
    return mock


def _jev_none_positive() -> MagicMock:
    """Jev noul says there is NO captcha (noul ≥ threshold)."""
    mock = MagicMock()
    mock.noul.return_value = JevAnswerNoul(noul=0.95)
    return mock


def _jev_choice_engine(engine: str) -> MagicMock:
    mock = MagicMock()
    mock.choice.return_value = JevAnswerChoice(choice=engine, probability=0.9)
    mock.noul.return_value = JevAnswerNoul(noul=0.1)  # not no-captcha
    return mock


class TestCaptchaRouterNoJev:
    """Router with no Jev client falls back to detector defaults."""

    def test_detects_family_without_jev(self) -> None:
        router = CaptchaRouter()
        result = router.route(FIXTURES["recaptcha"])
        assert result.family == "recaptcha"
        assert result.jev_confirmed is False

    def test_none_page_returns_none_engine(self) -> None:
        router = CaptchaRouter()
        result = router.route(FIXTURES["none"])
        assert result.family == "none"
        assert result.engine == "none"


class TestCaptchaRouterWithJev:
    def test_jev_confirms_engine(self) -> None:
        jev = _jev_choice_engine("image_ocr")
        router = CaptchaRouter(jev_client=jev)
        result = router.route(FIXTURES["image"])
        assert result.jev_confirmed is True
        assert result.engine == "image_ocr"

    def test_jev_pre_gate_short_circuits_none(self) -> None:
        jev = _jev_none_positive()
        router = CaptchaRouter(jev_client=jev)
        # Feed a very ambiguous page (low confidence detection)
        html = "<html><body><p>Hello</p></body></html>"
        result = router.route(html)
        assert result.family == "none"
        assert result.engine == "none"

    def test_jev_error_falls_back_to_default(self) -> None:
        jev = MagicMock()
        jev.noul.return_value = JevAnswerNoul(noul=0.1)
        jev.choice.side_effect = JevResponseError("bad response")
        router = CaptchaRouter(jev_client=jev)
        result = router.route(FIXTURES["text"])
        # Should fall back to default engine without crashing
        assert result.family == "text"
        assert result.engine == "text_reasoning"

    def test_jev_unknown_engine_falls_back(self) -> None:
        jev = _jev_choice_engine("unknown_engine_xyz")
        router = CaptchaRouter(jev_client=jev)
        result = router.route(FIXTURES["image"])
        # Unknown engine → default
        assert result.family == "image"
        assert result.engine == "image_ocr"  # default for image family
