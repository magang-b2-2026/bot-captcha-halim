from playwright.sync_api import sync_playwright

args = [
    '--host-resolver-rules=MAP democaptcha.com 77.222.40.38, MAP *.democaptcha.com 77.222.40.38'
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=args)
    page = browser.new_page()
    page.goto('https://democaptcha.com/demo-form-eng/image.html', timeout=15000)
    print('URL initial:', page.url)
    inputs = page.locator('input').all()
    for inp in inputs:
        print('Input:', inp.get_attribute('name'), inp.get_attribute('id'), inp.get_attribute('type'))
    btn = page.locator('input[type="submit"], button[type="submit"]').first
    print('Submit button:', btn.get_attribute('value') or btn.inner_text())
    browser.close()
