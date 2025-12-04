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
st.markdown("Track and compare daily mortgage rates from various banks and credit unions. Get notified when rates drop!")

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

df = load_data()
last_refreshed = None
best_rate_info = "Current Rates" # Default header

if df is not None and not df.empty:
    # Filter by latest date
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        last_refreshed = df["Date"].max()
        
        # Keep rows within 5 minutes of the last refresh
        time_threshold = last_refreshed - timedelta(minutes=5)
        df = df[df["Date"] >= time_threshold]
        
        # Drop Date column for display
        df = df.drop(columns=["Date"])
    elif "Timestamp" in df.columns:
        # Legacy support
        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
        last_refreshed = df["Timestamp"].max()
        df = df[df["Timestamp"] == last_refreshed]
        df = df.drop(columns=["Timestamp"])
        df = df.drop(columns=["Timestamp"])
    
    # Filters
    col_filter1, col_filter2 = st.columns(2)
    
    with col_filter1:
        # Filter by Loan Type
        if "Loan Type" in df.columns:
            loan_types = sorted(df["Loan Type"].unique().tolist())
            default_selection = ["Fixed 30"] if "Fixed 30" in loan_types else loan_types
            selected_types = st.multiselect("Filter by Loan Type", loan_types, default=default_selection)
            
            if selected_types:
                df = df[df["Loan Type"].isin(selected_types)]

    with col_filter2:
        # Search by Bank Name
        if "Bank Name" in df.columns:
            search_term = st.text_input("Search by Bank Name", placeholder="e.g. Delta")
            if search_term:
                df = df[df["Bank Name"].str.contains(search_term, case=False, na=False)]

    # Clean and Sort APR
    if "APR" in df.columns:
        def clean_apr(val):
            try:
                return float(str(val).replace("%", ""))
            except:
                return 100.0 

        df['APR_Value'] = df['APR'].apply(clean_apr)
        df = df.sort_values(by="APR_Value")
        
        # Calculate Best Rate for Header
        if not df.empty:
            best_row = df.iloc[0]
            best_rate = best_row.get("Rate", "N/A")
            best_apr = best_row.get("APR", "N/A")
            best_rate_info = f"Current Best Rate: {best_rate} and APR: {best_apr}"

        df = df.drop(columns=['APR_Value']) 

    # --- Refresh Logic Calculation ---
    refresh_disabled = False
    next_refresh_msg = ""
    if last_refreshed:
        time_since_refresh = datetime.now() - last_refreshed
        if time_since_refresh < timedelta(hours=24):
            refresh_disabled = True
            next_refresh_msg = f"Next refresh in {timedelta(hours=24) - time_since_refresh}"

    # Row 1: Header and Button
    col_header, col_refresh = st.columns([3, 1])
    
    with col_header:
        st.header(best_rate_info)
    
    with col_refresh:
        if st.button("Refresh Rates", disabled=refresh_disabled):
            with st.spinner("Scraping rates..."):
                import subprocess
                import sys
                
                try:
                    subprocess.run([sys.executable, "loan_rate_agent.py"], check=True)
                    st.success("Refreshed!")
                    st.rerun()
                except subprocess.CalledProcessError as e:
                    st.error(f"Error: {e}")
                except Exception as e:
                    st.error(f"Error: {e}")

    # Row 2: Captions (Aligned)
    col_cap_left, col_cap_right = st.columns([3, 1])
    
    with col_cap_left:
        if last_refreshed:
            st.caption(f"Last Refreshed: {last_refreshed}")
            
    with col_cap_right:
        if next_refresh_msg:
            st.caption(next_refresh_msg)

    # Map URLs for clickable Bank Name
    configs = load_configs()
    url_map = {cfg['name']: cfg['url'] for cfg in configs}
    
    if "Bank Name" in df.columns:
        def create_link(row):
            name = row["Bank Name"]
            url = url_map.get(name, "")
            if url:
                return f"{url}#{name}"
            return name 
            
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
    
    # --- Layout for Notifications and Add Bank ---
    st.divider()
    
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Get Notified")
        with st.form("email_form"):
            email = st.text_input("Enter your email to get notified when a better rate is available:")
            submitted = st.form_submit_button("Notify Me")
            if submitted:
                if email:
                    client = get_gspread_client()
                    if client:
                        sheet = get_sheet(client)
                        if sheet:
                            try:
                                try:
                                    ws = sheet.worksheet("Subscribers")
                                except gspread.WorksheetNotFound:
                                    try:
                                        ws = sheet.add_worksheet(title="Subscribers", rows=100, cols=2)
                                        ws.append_row(["Timestamp", "Email"])
                                    except:
                                        st.error("Could not create 'Subscribers' sheet.")
                                        ws = None
                                
                                if ws:
                                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    ws.append_row([timestamp, email])
                                    st.success(f"Subscribed {email}!")
                            except Exception as e:
                                st.error(f"Error saving email: {e}")
                else:
                    st.warning("Please enter an email address.")

    with col2:
        st.subheader("Add New Bank or Credit Union")
        # Wrap in form for outline consistency
        with st.form("add_bank_form"):
            new_url = st.text_input("Enter the URL of the page displaying mortgage rates", placeholder="http://www.example.com/mortgagerates")
            submitted_bank = st.form_submit_button("Add Bank")

            if submitted_bank:
                if not new_url:
                    st.warning("Please enter a URL.")
                else:
                    # Validate URL
                    from urllib.parse import urlparse
                    
                    def is_valid_url(url):
                        try:
                            result = urlparse(url)
                            return all([result.scheme, result.netloc])
                        except:
                            return False
                    
                    if not is_valid_url(new_url):
                        st.error("Please enter a valid URL (e.g., https://www.example.com).")
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
                                        else:
                                            # Extract found values for display
                                            found_values = new_config.pop("found_values", {})
                                            
                                            save_config(new_config)
                                            
                                            # Construct success message
                                            rates_msg = []
                                            new_rows = []
                                            
                                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            if last_refreshed:
                                                timestamp = last_refreshed.strftime("%Y-%m-%d %H:%M:%S")

                                            for label, data in found_values.items():
                                                rate = data['rate']
                                                apr = data['apr']
                                                rates_msg.append(f"{label}: {rate}")
                                                
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
                                    else:
                                        msg = "No rates found on page."
                                        st.error("Could not find any rates on the page. Please check the URL and ensure the rates are visible.")
                                except subprocess.CalledProcessError as e:
                                    st.error(f"Error analyzing URL: {e}")
                                except json.JSONDecodeError:
                                    st.error("Failed to parse configuration output.")
                                except Exception as e:
                                    st.error(f"Unexpected error: {e}")
