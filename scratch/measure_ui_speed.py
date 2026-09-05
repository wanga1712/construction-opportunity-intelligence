import time
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        t0 = time.time()
        print("Navigating to CRM Streamlit...")
        page.goto("http://10.8.0.13:8504")
        
        # Wait for Streamlit app to load completely
        page.wait_for_selector(".stApp")
        t1 = time.time()
        print(f"Page loaded (Streamlit container ready) in {t1 - t0:.2f} seconds")
        
        # Wait for spinner or check load completion
        # Streamlit loading indicator is at the top right: stApp [data-test-script-state="idle"]
        page.wait_for_selector('div[data-test-script-state="idle"]', timeout=30000)
        t2 = time.time()
        print(f"Streamlit script execution finished in {t2 - t0:.2f} seconds")
        
        browser.close()

if __name__ == "__main__":
    run()
