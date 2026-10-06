from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--host-resolver-rules=MAP democaptcha.com 77.222.40.38, MAP *.democaptcha.com 77.222.40.38'])
    page = browser.new_page()
    page.goto('https://democaptcha.com/demo-form-eng/image.html')
    msg = page.locator('textarea[name="message"]').first
    if msg.is_visible():
        msg.fill('Hello this is a test inquiry.')
    page.locator('input[name="vericode"]').first.fill('12345')
    page.locator('input[type="submit"]').first.click()
    page.wait_for_timeout(2000)
    print('URL after submit:', page.url)
    print('Body text:', page.locator('body').inner_text()[:400])
    browser.close()
