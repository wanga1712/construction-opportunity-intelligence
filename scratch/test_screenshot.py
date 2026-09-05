import os
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto("https://example.com")
        path = "C:/Users/Lenovo/.gemini/antigravity/brain/da7610a5-dc1b-4aac-9953-086d1220a9e4/test_screenshot.png"
        page.screenshot(path=path)
        print("Path exists:", os.path.exists(path))
        browser.close()

if __name__ == "__main__":
    run()
