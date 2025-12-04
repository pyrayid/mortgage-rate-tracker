import re
import csv
import json
import os
import toml
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- Google Sheets Setup ---
def get_gspread_client():
    # Try to load from secrets.toml (Streamlit Cloud / Local Dev)
    secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
    
    creds_dict = None
    
    if os.path.exists(secrets_path):
        try:
            secrets = toml.load(secrets_path)
            if "gcp_service_account" in secrets:
                creds_dict = secrets["gcp_service_account"]
        except Exception as e:
            print(f"Error loading secrets.toml: {e}")

    # Fallback: Check for local json file (if user kept it)
    if not creds_dict and os.path.exists("service_account.json"):
         with open("service_account.json") as f:
             creds_dict = json.load(f)

    if not creds_dict:
        print("Error: No GCP credentials found in secrets.toml or service_account.json")
        return None

    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def get_sheet(client, sheet_name="Mortgage Rates"):
    try:
        return client.open(sheet_name)
    except gspread.SpreadsheetNotFound:
        print(f"Error: Spreadsheet '{sheet_name}' not found. Please create it and share with the service account.")
        return None

def load_configs_from_sheet(client):
    sheet = get_sheet(client)
    if not sheet: return []
    
    try:
        worksheet = sheet.worksheet("Configs")
        records = worksheet.get_all_records()
        # Convert patterns string back to dict if stored as JSON string, or assume structure
        # For simplicity, let's assume the sheet has columns: name, url, patterns (JSON string), iframe_check
        
        configs = []
        for row in records:
            try:
                patterns = json.loads(row['patterns']) if isinstance(row['patterns'], str) else row['patterns']
                config = {
                    "name": row['name'],
                    "url": row['url'],
                    "iframe_check": row['iframe_check'] if row['iframe_check'] else None,
                    "patterns": patterns
                }
                configs.append(config)
            except Exception as e:
                print(f"Skipping invalid config row: {row} - {e}")
        return configs
    except gspread.WorksheetNotFound:
        print("Error: 'Configs' worksheet not found.")
        return []

def save_to_sheet(client, results):
    if not results: return
    sheet = get_sheet(client)
    if not sheet: return

    try:
        worksheet = sheet.worksheet("Rates")
    except gspread.WorksheetNotFound:
        print("Error: 'Rates' worksheet not found.")
        return

    # Prepare rows
    # Header: Date, Bank Name, Loan Type, Rate, APR
    rows = []
    for r in results:
        rows.append([r['Date'], r['Bank Name'], r['Loan Type'], r['Rate'], r['APR']])
    
    # Append
    worksheet.append_rows(rows)
    print(f"Appended {len(rows)} rows to 'Rates' sheet.")

def scrape_rates(configs):
    results = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        
        for config in configs:
            print(f"\n--- {config['name']} ---")
            print(f"Navigating to {config['url']}...")
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-US"
            )
            page = context.new_page()
            try:
                page.goto(config['url'], wait_until="commit", timeout=60000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                    page.wait_for_timeout(5000) 
                except:
                    print(f"Warning: Load timeout for {config['name']}, proceeding anyway...")
                    pass
                
                target_text = ""
                
                if config.get('iframe_check'):
                    found_frame = False
                    for frame in page.frames:
                        try:
                            frame_text = frame.inner_text("body")
                            if config['iframe_check'] in frame_text:
                                target_text = frame_text
                                found_frame = True
                                break
                        except:
                            continue
                    
                    if not found_frame:
                        print(f"Could not find iframe containing '{config['iframe_check']}'")
                        page.close()
                        continue
                else:
                    target_text = page.inner_text("body")
                
                for label, pattern in config['patterns'].items():
                    match = re.search(pattern, target_text, re.DOTALL | re.IGNORECASE)
                    if match:
                        rate = match.group(1)
                        apr = match.group(2)
                        print(f"{label}: Rate: {rate}%, APR: {apr}%")
                        results.append({
                            "Date": timestamp,
                            "Bank Name": config['name'],
                            "Loan Type": label,
                            "Rate": f"{rate}%",
                            "APR": f"{apr}%"
                        })
                    else:
                        print(f"Could not find rates for {label}")
                        
            except Exception as e:
                print(f"Error processing {config['name']}: {e}")
                results.append({
                    "Date": timestamp,
                    "Bank Name": config['name'],
                    "Loan Type": "Error",
                    "Rate": "Error",
                    "APR": "Error"
                })
            finally:
                page.close()
        
        browser.close()
    return results

def main():
    client = get_gspread_client()
    if not client: return

    configs = load_configs_from_sheet(client)
    if not configs:
        print("No configs found in Google Sheet.")
        return
    
    results = scrape_rates(configs)
    save_to_sheet(client, results)

if __name__ == "__main__":
    main()
