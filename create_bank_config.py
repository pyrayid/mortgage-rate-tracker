import argparse
import re
from playwright.sync_api import sync_playwright

def analyze_url(url, quiet=False):
    if not quiet:
        print(f"Analyzing {url}...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-http2", "--disable-blink-features=AutomationControlled"]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            page.goto(url, wait_until="commit", timeout=60000)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
            except:
                if not quiet:
                    print("Warning: Load timeout, proceeding with available content...")
        except Exception as e:
            if not quiet:
                print(f"Error navigating: {e}")
            browser.close()
            return None

        # 1. Determine Name
        title = page.title()
        name = title.split("|")[0].split("-")[0].strip()
        
        # 2. Find Content (Body vs Iframe)
        target_text = page.inner_text("body")
        iframe_check = None
        
        # Heuristic: If name doesn't look like a bank name, try to find one or fallback
        if "bank" not in name.lower() and "credit union" not in name.lower():
            # Try to find a better name in the text
            # Look for "X Bank" or "X Credit Union"
            name_match = re.search(r"([A-Z][a-zA-Z0-9'\s]+(?:Bank|Credit Union))", target_text)
            if name_match:
                name = name_match.group(1).strip()
            else:
                # Fallback to domain if still bad
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if "www." in domain:
                    domain = domain.replace("www.", "")
                name = domain.split('.')[0].title() + " (Auto-named)"
        
        if not quiet:
            print(f"Identified Bank Name: {name}")
        
        # Keywords to look for
        keywords = {
            "Fixed 30": ["30 Year Fixed", "Fixed 30", "30-Year Fixed", "Conventional 30", "Conforming 30"],
            "Fixed 15": ["15 Year Fixed", "Fixed 15", "15-Year Fixed", "Conventional 15", "Conforming 15"]
        }
        
        # Check if keywords are in body
        found_in_body = False
        for k_list in keywords.values():
            for k in k_list:
                if k.lower() in target_text.lower():
                    found_in_body = True
                    break
        
        if not found_in_body:
            if not quiet:
                print("Keywords not found in main body, checking frames...")
            for frame in page.frames:
                try:
                    ft = frame.inner_text("body")
                    for k_list in keywords.values():
                        for k in k_list:
                            if k.lower() in ft.lower():
                                target_text = ft
                                # Find a unique string in this frame to use as check
                                # Simple heuristic: use the keyword itself if unique enough, or a snippet
                                iframe_check = k 
                                if not quiet:
                                    print(f"Found content in iframe containing '{iframe_check}'")
                                break
                        if iframe_check: break
                    if iframe_check: break
                except:
                    continue
        
        # 3. Generate Patterns
        patterns = {}
        found_values = {}
        
        for label, search_terms in keywords.items():
            for term in search_terms:
                # Find the term in text
                # We want to match case-insensitive for finding, but preserve text for regex generation
                # Actually, let's just use regex to find the term location
                
                # Regex to find term followed by some text and then a percentage
                # pattern: term ... number.number% ... number.number%
                
                # We construct a broad regex to capture the segment
                # term + (up to 150 chars) + rate% + (up to 50 chars) + apr%
                
                # Updated to capture up to 3 percentages to handle "Points"
                base_pattern = re.escape(term) + r".{0,150}?(\d+\.\d+)\s*%.{0,50}?(\d+\.\d+)\s*%(?:.{0,50}?(\d+\.\d+)\s*%)?"
                
                try:
                    regex_match = re.search(base_pattern, target_text, re.DOTALL | re.IGNORECASE)
                    if regex_match:
                        if not quiet:
                            print(f"Found match for {label} using term '{term}'")
                        
                        clean_term = term.replace(" ", r"\s*") # Allow flexible whitespace in term
                        
                        # Logic to determine which groups are Rate and APR
                        v1 = float(regex_match.group(1))
                        v2 = float(regex_match.group(2))
                        v3 = float(regex_match.group(3)) if regex_match.lastindex >= 3 else None
                        
                        rate_val = v1
                        apr_val = v2
                        
                        # Heuristic: APR should be >= Rate (usually)
                        # If v2 < v1, v2 might be points. Check v3.
                        if v3 is not None and v2 < v1:
                            # Assume v2 is points, v3 is APR
                            apr_val = v3
                            # Construct pattern to skip the middle percentage
                            final_pattern = clean_term + r".*?(\d+\.\d+)\s*%.*?(?:\d+\.\d+\s*%).*?(\d+\.\d+)\s*%"
                        else:
                            final_pattern = clean_term + r".*?(\d+\.\d+)\s*%.*?(\d+\.\d+)\s*%"
                        
                        patterns[label] = final_pattern
                        found_values[label] = {"rate": f"{rate_val}%", "apr": f"{apr_val}%"}
                        break 
                except Exception as e:
                    if not quiet:
                        print(f"Error in regex matching for {label}: {e}")
            
            # If no match found with standard terms, try looking for table row structure
            # e.g. "30 ... 0.000% ... 6.125% ... 6.147%"
            if label not in patterns:
                try:
                    # Look for "30" or "15" at start of line/row followed by percentages
                    years = "30" if "30" in label else "15"
                    # Pattern: years + (optional text) + 0.000% (points) + rate% + apr%
                    # We look for the sequence of percentages
                    
                    # Specific for Provident-style tables:
                    # "30 0.000% 6.125% 6.147%"
                    # Updated to handle potential points column
                    table_pattern = r"(?<!\d)" + years + r"\s+(?:[a-zA-Z\s]+\s+)?(?:0\.000%|\d+\.\d+%)\s+(\d+\.\d+)%\s+(\d+\.\d+)%"
                    
                    # Check for 3 numbers case too
                    table_pattern_3 = r"(?<!\d)" + years + r"\s+(?:[a-zA-Z\s]+\s+)?(\d+\.\d+)%\s+(\d+\.\d+)%\s+(\d+\.\d+)%"
                    
                    table_match = re.search(table_pattern_3, target_text, re.DOTALL | re.IGNORECASE)
                    if table_match:
                         # Check values
                        v1 = float(table_match.group(1))
                        v2 = float(table_match.group(2))
                        v3 = float(table_match.group(3))
                        
                        if v2 < v1: # v2 is points?
                             patterns[label] = r"(?<!\d)" + years + r"\s+(?:[a-zA-Z\s]+\s+)?(\d+\.\d+)%\s+(?:\d+\.\d+%)\s+(\d+\.\d+)%"
                             found_values[label] = {"rate": f"{v1}%", "apr": f"{v3}%"}
                        else:
                             patterns[label] = r"(?<!\d)" + years + r"\s+(?:[a-zA-Z\s]+\s+)?(\d+\.\d+)%\s+(\d+\.\d+)%"
                             found_values[label] = {"rate": f"{v1}%", "apr": f"{v2}%"}
                    else:
                        table_match = re.search(table_pattern, target_text, re.DOTALL | re.IGNORECASE)
                        if table_match:
                            if not quiet:
                                print(f"Found table match for {label}")
                            patterns[label] = table_pattern
                            found_values[label] = {"rate": f"{table_match.group(1)}%", "apr": f"{table_match.group(2)}%"}
                except Exception as e:
                    if not quiet:
                        print(f"Error in table matching for {label}: {e}")
        
        browser.close()
        
        if not patterns:
            if not quiet:
                print("No matching rates found on the page.")
            return None

        # 4. Output Config
        new_config = {
            "name": name,
            "url": url,
            "iframe_check": iframe_check,
            "patterns": patterns,
            "found_values": found_values
        }
        return new_config

def generate_config(url):
    new_config = analyze_url(url)
    if not new_config:
        print("Failed to generate config.")
        return

    print("\n--- Generated Config ---\n")
    print(new_config)
    print("\n------------------------")
    
    save = input("Save this config to bank_configs.json? (y/n): ")
    if save.lower() == 'y':
        import json
        import os
        
        configs = []
        if os.path.exists("bank_configs.json"):
            with open("bank_configs.json", "r") as f:
                try:
                    configs = json.load(f)
                except:
                    pass
        
        configs.append(new_config)
        
        with open("bank_configs.json", "w") as f:
            json.dump(configs, f, indent=4)
        print("Config saved to bank_configs.json")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate bank config for loan scraper")
    parser.add_argument("url", help="URL of the rates page")
    parser.add_argument("--json", action="store_true", help="Output only JSON config")
    args = parser.parse_args()
    
    if args.json:
        import json
        config = analyze_url(args.url, quiet=True)
        if config:
            print(json.dumps(config))
    else:
        generate_config(args.url)
