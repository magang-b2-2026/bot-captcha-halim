from pathlib import Path
from playwright.sync_api import sync_playwright

from komdigi_bot.solvers.llm import llm_from_settings

args = ['--host-resolver-rules=MAP democaptcha.com 77.222.40.38, MAP *.democaptcha.com 77.222.40.38']

llm = llm_from_settings()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=args)
    page = browser.new_page()
    page.goto('https://democaptcha.com/demo-form-eng/image.html')

    # Find captcha image element
    img_el = page.locator('img[src*="get_captcha"], img#captcha').first
    img_path = Path("democaptcha_test.png")
    img_el.screenshot(path=str(img_path))
    print("Screenshot saved, calling Gemini vision...")

    ans = llm.ask_vision(
        img_path,
        "Transcribe the CAPTCHA text in this image. Return ONLY the alphanumeric characters, nothing else."
    )
    print("Gemini answer:", ans)

    # Fill message if present
    textarea = page.locator('textarea').first
    if textarea.is_visible():
        textarea.fill('Automated QA verification test message.')

    # Fill vericode
    page.locator('input[name="vericode"], input#vericode').first.fill(ans.strip())
    page.locator('input[type="submit"]').first.click()
    page.wait_for_timeout(3000)

    print("Post-submit URL:", page.url)
    body_text = page.locator('body').inner_text()
    print("Post-submit body snippet:", body_text[:500])

    if "invalid" in body_text.lower() or "error" in body_text.lower():
        print("RESULT: FAILED")
    else:
        print("RESULT: PASSED!")

    browser.close()
