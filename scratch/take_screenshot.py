import sys
import os
import time
from playwright.sync_api import sync_playwright

def main():
    dest_dir = r"C:\Users\Lenovo\.gemini\antigravity\brain\da7610a5-dc1b-4aac-9953-086d1220a9e4"
    dest_path = os.path.join(dest_dir, "monitoring_status.png")
    os.makedirs(dest_dir, exist_ok=True)
    
    with sync_playwright() as p:
        print("Launching browser...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # Set viewport size
        page.set_viewport_size({"width": 1280, "height": 1000})
        print("Navigating to http://10.8.0.13:8504...")
        page.goto("http://10.8.0.13:8504", timeout=60000)
        
        time.sleep(8) # Wait for page loading/rendering
        
        # Click the system health button
        print("Clicking 'Состояние серверов' button...")
        page.click("button:has-text('Состояние серверов')")
        
        print("Waiting for page load...")
        time.sleep(10)
        
        print("Taking screenshot...")
        page.screenshot(path=dest_path, full_page=True)
        print(f"Screenshot saved to {dest_path}")
        browser.close()

if __name__ == "__main__":
    main()
