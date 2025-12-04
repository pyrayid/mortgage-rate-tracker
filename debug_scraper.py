from playwright.sync_api import sync_playwright

def debug_url(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-http2",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US"
        )
        page = context.new_page()
        print(f"Navigating to {url}...")
        page.goto(url)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        
        text = page.inner_text("body")
        with open("page_content.txt", "w", encoding="utf-8") as f:
            f.write(text)
        print("Page content saved to page_content.txt")
        browser.close()

if __name__ == "__main__":
    debug_url("https://www.robinsfcu.org/mortgage-loans#mortgage-rates")
