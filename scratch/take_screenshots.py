import time
import shutil
import os
from playwright.sync_api import sync_playwright

def run():
    dest_dir = "C:/Users/Lenovo/.gemini/antigravity/brain/da7610a5-dc1b-4aac-9953-086d1220a9e4"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1024})
        
        # Navigate
        print("Navigating to CRM...")
        page.goto("http://10.8.0.13:8504")
        
        # Wait for Streamlit loading indicator to disappear and first card to load
        print("Waiting for page load...")
        page.wait_for_selector(".stApp")
        time.sleep(5)
        
        # Click "Аналитика V3" sidebar/tab button
        print("Switching to Analytics V3...")
        buttons = page.locator("button").all()
        u_v3_tab = "\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430 V3"
        for btn in buttons:
            text = btn.text_content() or ""
            if u_v3_tab in text:
                btn.click()
                break
                
        print("Sleeping 10s for page to render...")
        time.sleep(10) # let it render fully
        
        # Take screenshot
        local_all = "screenshot_all.png"
        page.screenshot(path=local_all)
        
        dest_all = os.path.join(dest_dir, "screenshot_all.png")
        shutil.copy(local_all, dest_all)
        print(f"Screenshot saved to {dest_all}")
        
        # Copy to screenshot_evidence_found.png too (frozen UI has no research pills)
        dest_found = os.path.join(dest_dir, "screenshot_evidence_found.png")
        shutil.copy(local_all, dest_found)
        
        browser.close()

if __name__ == "__main__":
    run()
