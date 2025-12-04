import streamlit as st
import pandas as pd
import json
import os
import toml
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import loan_rate_agent
import create_bank_config

st.set_page_config(page_title="Mortgage Rate Tracker", layout="wide")

st.title("Mortgage Rate Tracker")

# --- Google Sheets Helper ---
@st.cache_resource
def get_gspread_client():
    # Try to load from secrets.toml (Streamlit Cloud / Local Dev)
    # Streamlit handles secrets automatically via st.secrets
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = st.secrets["gcp_service_account"]
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            return client
    except Exception as e:
        st.error(f"Error loading secrets: {e}")
    return None

def get_sheet(client, sheet_name="Mortgage Rates"):
    try:
        return client.open(sheet_name)
    except gspread.SpreadsheetNotFound:
        st.error(f"Spreadsheet '{sheet_name}' not found. Please create it and share with the service account.")
        return None

# --- Helper Functions ---
def load_data():
    client = get_gspread_client()
    if not client: return None
    
    sheet = get_sheet(client)
    if not sheet: return None
    
    try:
        worksheet = sheet.worksheet("Rates")
        data = worksheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            return df
        return pd.DataFrame() # Empty DF
    except gspread.WorksheetNotFound:
        st.error("'Rates' worksheet not found.")
        return None
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None

def load_configs():
    client = get_gspread_client()
    if not client: return []
    
    sheet = get_sheet(client)
    if not sheet: return []
    
    try:
        worksheet = sheet.worksheet("Configs")
        records = worksheet.get_all_records()
        configs = []
        for row in records:
            try:
                # Handle patterns if stored as string
                patterns = json.loads(row['patterns']) if isinstance(row['patterns'], str) else row['patterns']
                config = {
                    "name": row['name'],
                    "url": row['url'],
                    "iframe_check": row['iframe_check'] if row['iframe_check'] else None,
                    "patterns": patterns
                }
                configs.append(config)
            except:
                pass
        return configs
    except:
        return []

def save_config(new_config):
    client = get_gspread_client()
    if not client: return
    
    sheet = get_sheet(client)
    if not sheet: return
    
    try:
        worksheet = sheet.worksheet("Configs")
        # Columns: name, url, patterns, iframe_check
        row = [
            new_config['name'],
            new_config['url'],
            json.dumps(new_config['patterns']),
            new_config['iframe_check'] or ""
        ]
        worksheet.append_row(row)
    except Exception as e:
        st.error(f"Error saving config: {e}")

# --- Main Dashboard ---

st.header("Current Rates")

df = load_data()
last_refreshed = None

if df is not None and not df.empty:
    # Filter by latest date
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        last_refreshed = df["Date"].max()
        st.write(f"**Last Refreshed:** {last_refreshed}")
        
        # Keep rows within 5 minutes of the last refresh (to handle legacy data with varying timestamps)
        time_threshold = last_refreshed - timedelta(minutes=5)
        df = df[df["Date"] >= time_threshold]
        
        # Drop Date column for display
        df = df.drop(columns=["Date"])
    elif "Timestamp" in df.columns:
        # Legacy support just in case
        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
        last_refreshed = df["Timestamp"].max()
        st.write(f"**Last Refreshed:** {last_refreshed}")
        df = df[df["Timestamp"] == last_refreshed]
        df = df.drop(columns=["Timestamp"])
        df = df.drop(columns=["Timestamp"])
    
    # Filter by Loan Type
    if "Loan Type" in df.columns:
        loan_types = sorted(df["Loan Type"].unique().tolist())
        # Default to "Fixed 30" if available, otherwise all
        default_selection = ["Fixed 30"] if "Fixed 30" in loan_types else loan_types
        selected_types = st.multiselect("Filter by Loan Type", loan_types, default=default_selection)
        
        if selected_types:
            df = df[df["Loan Type"].isin(selected_types)]
        else:
            # If nothing selected, show nothing? Or show all? Usually show nothing or all.
            # Let's show nothing to indicate filter is active but empty, or maybe just don't filter?
            # Standard behavior is usually "if empty, show all" OR "if empty, show nothing".
            # Let's go with: if user clears selection, show nothing (matches UI expectation).
            df = df[df["Loan Type"].isin(selected_types)]

    # Clean and Sort APR
    if "APR" in df.columns:
        # Create a temporary column for sorting
        # Remove % and convert to float, handle 'Error'
        def clean_apr(val):
            try:
                return float(val.replace("%", ""))
            except:
                return 100.0 # Push errors to bottom

        df['APR_Value'] = df['APR'].apply(clean_apr)
        df = df.sort_values(by="APR_Value")
        df = df.drop(columns=['APR_Value']) # Remove temp column

    # Map URLs for clickable Bank Name
    configs = load_configs()
    url_map = {cfg['name']: cfg['url'] for cfg in configs}
    
    if "Bank Name" in df.columns:
        # Create a link with the name as a fragment for display_text extraction
        # Format: url#Bank Name
        def create_link(row):
            name = row["Bank Name"]
            url = url_map.get(name, "")
            if url:
                return f"{url}#{name}"
            return name # Fallback to just name if no URL found
            
        df["Bank Name"] = df.apply(create_link, axis=1)

    st.dataframe(
        df,
        hide_index=True,
        column_config={
            "Bank Name": st.column_config.LinkColumn(
                "Bank Name",
                display_text=r"#(.+)"
            )
        }
    )
else:
    st.info("No data available yet.")

# --- Refresh Logic ---
refresh_disabled = False
if last_refreshed:
    time_since_refresh = datetime.now() - last_refreshed
    if time_since_refresh < timedelta(hours=24):
        refresh_disabled = True
        st.caption(f"Refresh available in {timedelta(hours=24) - time_since_refresh}")

if st.button("Refresh Rates", disabled=refresh_disabled):
    with st.spinner("Scraping rates... This may take a minute."):
        import subprocess
        import sys
        
        try:
            # Run the agent as a separate process to avoid asyncio loop conflicts
            subprocess.run([sys.executable, "loan_rate_agent.py"], check=True)
            st.success("Rates refreshed!")
            st.rerun()
        except subprocess.CalledProcessError as e:
            st.error(f"Error refreshing rates: {e}")
        except Exception as e:
            st.error(f"Unexpected error: {e}")

def log_submission(url, status, details):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    client = get_gspread_client()
    if client:
        sheet = get_sheet(client)
        if sheet:
            try:
                # Try to get Logs worksheet, create if missing (or just fail gracefully)
                try:
                    ws = sheet.worksheet("Logs")
                    ws.append_row([timestamp, url, status, details])
                except gspread.WorksheetNotFound:
                    # Optional: Create it if you want, or just error
                    # For now, let's assume user created it or we just skip
                    print("Logs sheet not found, skipping log.")
            except Exception as e:
                print(f"Error logging to sheet: {e}")
    
    # Also print to console
    print(f"[{timestamp}] URL: {url} | Status: {status} | Details: {details}")

# --- Add New Bank ---
st.divider()
st.header("Add New Bank or Credit Union")

new_url = st.text_input("Enter URL for page containing loan rates.")

if st.button("Add Bank"):
    if not new_url:
        st.warning("Please enter a URL.")
    else:
        # Check if already exists
        configs = load_configs()
        exists = False
        for config in configs:
            if config['url'] == new_url:
                exists = True
                break
        
        if exists:
            msg = "Bank already tracked by URL."
            st.warning(msg)
            log_submission(new_url, "Skipped", msg)
        else:
            with st.spinner("Analyzing URL..."):
                import subprocess
                import sys
                
                try:
                    # Run config generator in subprocess
                    result = subprocess.check_output(
                        [sys.executable, "create_bank_config.py", new_url, "--json"],
                        text=True
                    )
                    
                    if result.strip():
                        new_config = json.loads(result)
                        
                        # Check if name already exists
                        name_exists = False
                        for config in configs:
                            if config['name'] == new_config['name']:
                                name_exists = True
                                break
                        
                        if name_exists:
                            msg = f"Bank with name '{new_config['name']}' already exists."
                            st.error(msg)
                            log_submission(new_url, "Failed", msg)
                        else:
                            # Extract found values for display
                            found_values = new_config.pop("found_values", {})
                            
                            save_config(new_config)
                            
                            # Construct success message
                            rates_msg = []
                            new_rows = []
                            
                            # Determine timestamp (use latest from CSV or now)
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            if last_refreshed:
                                timestamp = last_refreshed.strftime("%Y-%m-%d %H:%M:%S")

                            for label, data in found_values.items():
                                rate = data['rate']
                                apr = data['apr']
                                rates_msg.append(f"{label}: {rate}")
                                
                                # Prepare row for CSV
                                new_rows.append({
                                    "Date": timestamp,
                                    "Bank Name": new_config['name'],
                                    "Loan Type": label,
                                    "Rate": rate,
                                    "APR": apr
                                })
                            
                            # Append to Sheet
                            if new_rows:
                                client = get_gspread_client()
                                if client:
                                    sheet = get_sheet(client)
                                    if sheet:
                                        try:
                                            ws = sheet.worksheet("Rates")
                                            rows = [[r['Date'], r['Bank Name'], r['Loan Type'], r['Rate'], r['APR']] for r in new_rows]
                                            ws.append_rows(rows)
                                        except:
                                            pass

                            rates_str = " and ".join(rates_msg)
                            msg = f"Successfully found Mortgage Loan Rates {rates_str}, added to list! (Refresh to view)"
                            
                            st.success(msg)
                            log_submission(new_url, "Success", f"Added {new_config['name']}")
                    else:
                        msg = "No rates found on page."
                        st.error("Could not find any rates on the page. Please check the URL and ensure the rates are visible.")
                        log_submission(new_url, "Failed", msg)
                except subprocess.CalledProcessError as e:
                    st.error(f"Error analyzing URL: {e}")
                    log_submission(new_url, "Error", str(e))
                except json.JSONDecodeError:
                    st.error("Failed to parse configuration output.")
                    log_submission(new_url, "Error", "JSON Decode Error")
                except Exception as e:
                    st.error(f"Unexpected error: {e}")
                    log_submission(new_url, "Error", str(e))
