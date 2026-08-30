import os
import re
import sys
import time
from playwright.sync_api import sync_playwright

def main():
    url = os.environ.get("STREAMLIT_APP_URL")
    if not url:
        print("Error: STREAMLIT_APP_URL environment variable is not set.")
        sys.exit(1)
        
    print(f"Visiting Streamlit App URL: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto(url, timeout=60000)
            time.sleep(5) # Wait for page rendering
            
            # Search for any button text commonly used by Streamlit Cloud for wake up
            wake_up_button = page.get_by_role("button", name=re.compile("wake|back up|get this", re.IGNORECASE))
            
            if wake_up_button.count() > 0:
                print("App is sleeping! Clicking wake-up button...")
                wake_up_button.first.click()
                print("Waiting for app to wake up...")
                page.wait_for_timeout(20000)
                print("App wake up triggered successfully.")
            else:
                print("App is already awake! Registered keep-alive traffic.")
                
            page.screenshot(path="screenshot.png")
            print("Screenshot saved to screenshot.png")
            
        except Exception as e:
            print(f"An error occurred during keep-alive: {e}")
            try:
                page.screenshot(path="error_screenshot.png")
            except:
                pass
            sys.exit(1)
        finally:
            browser.close()

if __name__ == "__main__":
    main()
