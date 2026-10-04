"""
tests/test_qa_four_challenges.py
QA verification suite for the 4 requested target challenge types:
1. https://democaptcha.com/demo-form-eng/image.html
2. https://2captcha.com/demo/text
3. http://democaptcha.com/demo-form-eng/math-image.html
4. https://2captcha.com/demo/normal
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import sync_playwright

from komdigi_bot.solvers.base import SolveStatus
from komdigi_bot.solvers.image_ocr import ImageOCRSolver
from komdigi_bot.solvers.text_reasoning import TextReasoningSolver
from komdigi_bot.triage.detector import CaptchaDetector
from komdigi_bot.triage.router import CaptchaRouter


# Fixtures replicating the actual DOM of the 4 targets
FIXTURE_DEMOCAPTCHA_IMAGE = """
<!DOCTYPE html>
<html>
<head><title>Demo Form Image Captcha - DemoCaptcha</title></head>
<body>
  <h2>Demo Form with Image Captcha</h2>
  <form action="" method="post" id="demo-form">
    <p>Please enter the characters shown below:</p>
    <img id="captcha" src="/get_captcha.php?v=1" alt="captcha image" width="150" height="50">
    <br>
    <input type="text" name="captcha" id="captcha-input" placeholder="Enter captcha code">
    <input type="submit" value="Submit Form" id="submit-btn">
  </form>
</body>
</html>
"""

FIXTURE_2CAPTCHA_TEXT = """
<!DOCTYPE html>
<html>
<head><title>Text Captcha Demo - 2Captcha</title></head>
<body>
  <h2>Text captcha demo</h2>
  <form action="" method="post" class="text-captcha">
    <p class="question">What color is the clear daytime sky?</p>
    <input type="text" id="answer" name="answer" placeholder="Enter answer here">
    <button type="submit" id="submit">Check</button>
  </form>
</body>
</html>
"""

FIXTURE_DEMOCAPTCHA_MATH = """
<!DOCTYPE html>
<html>
<head><title>Demo Form Math Image Captcha - DemoCaptcha</title></head>
<body>
  <h2>Demo Form with Math Image Captcha</h2>
  <form action="" method="post" id="demo-form">
    <p>Please solve the equation in the image:</p>
    <img id="captcha" src="/get_captcha.php?math=1" alt="math captcha image" width="150" height="50">
    <br>
    <input type="text" name="keystring" id="keystring" placeholder="Enter answer">
    <input type="submit" value="Send Message" id="submit-btn">
  </form>
</body>
</html>
"""

FIXTURE_2CAPTCHA_NORMAL = """
<!DOCTYPE html>
<html>
<head><title>Normal Captcha Demo - 2Captcha</title></head>
<body>
  <h2>Normal Captcha Demo</h2>
  <form action="" method="post">
    <img src="/captcha.jpg" alt="normal captcha" width="120" height="40">
    <input type="text" name="captcha" placeholder="Enter answer here">
    <button type="submit">Check</button>
  </form>
</body>
</html>
"""


def test_triage_detection_four_targets():
    """Verify CaptchaDetector accurately identifies all 4 target families with high confidence."""
    detector = CaptchaDetector()

    # 1. Democaptcha Image
    res1 = detector.detect(FIXTURE_DEMOCAPTCHA_IMAGE)
    assert res1.family == "image"
    assert res1.confidence >= 0.8

    # 2. 2Captcha Text
    res2 = detector.detect(FIXTURE_2CAPTCHA_TEXT)
    assert res2.family == "text"
    assert res2.confidence >= 0.8

    # 3. Democaptcha Math Image
    res3 = detector.detect(FIXTURE_DEMOCAPTCHA_MATH)
    assert res3.family == "image"
    assert res3.confidence >= 0.8

    # 4. 2Captcha Normal Image
    res4 = detector.detect(FIXTURE_2CAPTCHA_NORMAL)
    assert res4.family == "image"
    assert res4.confidence >= 0.8


def test_routing_engine_mapping():
    """Verify CaptchaRouter routes all 4 targets to the correct solver engines."""
    router = CaptchaRouter()

    r1 = router.route(FIXTURE_DEMOCAPTCHA_IMAGE, "https://democaptcha.com/demo-form-eng/image.html")
    assert r1.family == "image"
    assert r1.engine == "image_ocr"

    r2 = router.route(FIXTURE_2CAPTCHA_TEXT, "https://2captcha.com/demo/text")
    assert r2.family == "text"
    assert r2.engine == "text_reasoning"

    r3 = router.route(FIXTURE_DEMOCAPTCHA_MATH, "http://democaptcha.com/demo-form-eng/math-image.html")
    assert r3.family == "image"
    assert r3.engine == "image_ocr"

    r4 = router.route(FIXTURE_2CAPTCHA_NORMAL, "https://2captcha.com/demo/normal")
    assert r4.family == "image"
    assert r4.engine == "image_ocr"


def test_e2e_solving_flow_simulation(tmp_path: Path):
    """Simulate complete browser interaction for all 4 targets using Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Test Democaptcha Image OCR
        mock_llm_vision = MagicMock()
        mock_llm_vision.ask_vision.return_value = "W9H5K"
        mock_llm_vision._vision_model = "ag/gemini-3.8-flash-high"
        solver_img = ImageOCRSolver(mock_llm_vision)

        page.set_content(FIXTURE_DEMOCAPTCHA_IMAGE)
        # Mock successful submission DOM modification on click
        page.evaluate("""() => {
            document.getElementById('submit-btn').addEventListener('click', (e) => {
                e.preventDefault();
                document.body.innerHTML += '<h1>Your message has been sent successfully!</h1>';
            });
        }""")
        attempt_img = solver_img.solve(page, tmp_path)
        assert attempt_img.status == SolveStatus.PASS
        assert attempt_img.answer == "W9H5K"

        # 2. Test 2Captcha Text Reasoning
        mock_llm_text = MagicMock()
        mock_llm_text.ask_text.return_value = "blue"
        mock_llm_text._reasoning_model = "ag/gemini-3.8-flash-high"
        solver_txt = TextReasoningSolver(mock_llm_text)

        page.set_content(FIXTURE_2CAPTCHA_TEXT)
        page.evaluate("""() => {
            document.getElementById('submit').addEventListener('click', (e) => {
                e.preventDefault();
                document.body.innerHTML += '<p>Captcha is passed successfully</p>';
            });
        }""")
        attempt_txt = solver_txt.solve(page, tmp_path)
        assert attempt_txt.status == SolveStatus.PASS
        assert attempt_txt.answer == "blue"

        # 3. Test Democaptcha Math Image OCR (Math equation evaluation)
        mock_llm_math = MagicMock()
        # Vision model returns computed result 14 for "9 + 5"
        mock_llm_math.ask_vision.return_value = "14"
        mock_llm_math._vision_model = "ag/gemini-3.8-flash-high"
        solver_math = ImageOCRSolver(mock_llm_math)

        page.set_content(FIXTURE_DEMOCAPTCHA_MATH)
        page.evaluate("""() => {
            document.getElementById('submit-btn').addEventListener('click', (e) => {
                e.preventDefault();
                document.body.innerHTML += '<div>Form submitted successfully</div>';
            });
        }""")
        attempt_math = solver_math.solve(page, tmp_path)
        assert attempt_math.status == SolveStatus.PASS
        assert attempt_math.answer == "14"

        # 4. Test 2Captcha Normal Image
        mock_llm_norm = MagicMock()
        mock_llm_norm.ask_vision.return_value = "AB72"
        mock_llm_norm._vision_model = "ag/gemini-3.8-flash-high"
        solver_norm = ImageOCRSolver(mock_llm_norm)

        page.set_content(FIXTURE_2CAPTCHA_NORMAL)
        page.evaluate("""() => {
            document.querySelector('button[type="submit"]').addEventListener('click', (e) => {
                e.preventDefault();
                document.body.innerHTML += '<p>Captcha is passed successfully</p>';
            });
        }""")
        attempt_norm = solver_norm.solve(page, tmp_path)
        assert attempt_norm.status == SolveStatus.PASS
        assert attempt_norm.answer == "AB72"

        browser.close()
