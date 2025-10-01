from camoufox.sync_api import Camoufox

# headless="virtual" активирует Xvfb (нужен пакет xvfb)
with Camoufox(headless="virtual", geoip=True) as browser:
    page = browser.new_page()
    page.goto("https://example.com")
    print("Title:", page.title())
