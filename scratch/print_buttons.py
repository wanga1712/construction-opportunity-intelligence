import time
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("http://10.8.0.13:8504")
        page.wait_for_selector(".stApp")
        
        time.sleep(5)
        
        buttons = page.locator("button").all()
        for idx, btn in enumerate(buttons):
            text = btn.text_content() or ""
            print(f"Button {idx}: {repr(text)}")
            
        browser.close()

if __name__ == "__main__":
    run()
