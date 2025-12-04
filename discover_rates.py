from playwright.sync_api import sync_playwright

def discover():
    urls = [
        "https://www.cdcfcu.com/rates/home-loans/",
        "https://www.georgiasown.org/rates-mortgage"
    ]
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for url in urls:
            print(f"--- Visiting {url} ---")
            page = browser.new_page()
            page.goto(url)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
            
            # Get all text
            text = page.inner_text("body")
            print(f"Text length: {len(text)}")
            
            # Look for keywords
            keywords = ["Fixed 30", "30 Year", "Rates", "%", "Mortgage"]
            for kw in keywords:
                count = text.count(kw)
                print(f"Keyword '{kw}' found {count} times")
                if count > 0:
                    idx = text.find(kw)
                    print(f"Context: {text[idx:idx+100].replace('\n', ' ')}")
            
            if len(text) < 2000:
                print(f"Full text dump: {text}")
                
            # Check for iframes
            frames = page.frames
            print(f"Frames found: {len(frames)}")
            for frame in frames:
                try:
                    frame_text = frame.inner_text("body")
                    if "Fixed" in frame_text:
                        print(f"Found 'Fixed' in frame: {frame.url}")
                        print(f"Frame text snippet: {frame_text[:200]}")
                except:
                    pass
            
            print("\n")
            page.close()
            
        browser.close()

if __name__ == "__main__":
    discover()
