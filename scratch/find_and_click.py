import time
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("http://10.8.0.13:8504")
        page.wait_for_selector(".stApp")
        
        time.sleep(10)
        
        buttons = page.locator("button").all()
        lines = []
        for idx, btn in enumerate(buttons):
            text = btn.text_content() or ""
            lines.append(f"{idx}: {repr(text)}")
            
        with open("C:/Users/Lenovo/.gemini/antigravity/brain/da7610a5-dc1b-4aac-9953-086d1220a9e4/buttons.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            
        browser.close()

if __name__ == "__main__":
    run()
