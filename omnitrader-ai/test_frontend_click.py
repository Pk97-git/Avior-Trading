from playwright.sync_api import sync_playwright
import time

def test_universe_click():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("Navigating to dashboard...")
        page.goto("http://localhost:5173")
        
        print("Waiting for dashboard to load...")
        # Wait for the status cards
        page.wait_for_selector("text=Stock Universe", timeout=10000)
        
        print("Clicking Stock Universe card...")
        # Find the card with "Stock Universe" label and click it
        page.locator("h3:has-text('Stock Universe')").locator("..").click()
        
        print("Waiting for Universe table to populate...")
        # Wait for a row in the DataPreview table
        page.wait_for_selector("tbody tr", timeout=10000)
        
        print("Clicking first row...")
        page.locator("tbody tr").first.click()
        
        print("Waiting for detail view modal...")
        try:
            # The header has "Stock Analysis" badge
            page.wait_for_selector("text=Stock Analysis", timeout=5000)
            print("SUCCESS: Detail view opened.")
        except Exception as e:
            # Check for alert dialogue presence
            page.on("dialog", lambda dialog: print(f"ALERT: {dialog.message}"))
            time.sleep(2) # Give alert time to print 
            print("FAILED: Modal did not appear.")
            print(str(e))
        
        browser.close()

if __name__ == "__main__":
    test_universe_click()
