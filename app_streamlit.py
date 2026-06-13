import streamlit as st
import pandas as pd
import requests
import os
import time
from datetime import datetime, timedelta
class DotDict(dict):
    """A dictionary subclass that supports accessing keys as attributes (dot-notation)."""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

# Set page config
st.set_page_config(
    page_title="Smart Accounting Hub",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom premium CSS with Outfit/Inter typography, Glassmorphism, and Micro-animations
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&family=Inter:wght@300;400;500;600;700&display=swap');
    
    /* Global Typography - DO NOT override 'span' globally to protect Streamlit internal icons */
    html, body, [data-testid="stAppViewContainer"], .main, .stMarkdown, p, label, li {
        font-family: 'Inter', sans-serif !important;
        color: var(--text-color) !important;
    }
    
    h1, h2, h3, h4, h5, h6, .outfit-font {
        font-family: 'Outfit', sans-serif !important;
        font-weight: 700 !important;
        color: var(--text-color) !important;
    }

    /* Premium Cards */
    .glass-card {
        background: var(--background-color) !important;
        border: 1px solid rgba(128, 128, 128, 0.2) !important;
        border-radius: 16px !important;
        padding: 24px !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03) !important;
        margin-bottom: 24px !important;
    }
    
    /* Premium Styled Metric Cards */
    div[data-testid="stMetric"] {
        background: var(--background-color) !important;
        border: 1px solid rgba(128, 128, 128, 0.15) !important;
        border-radius: 16px !important;
        padding: 16px 20px !important;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05), 0 1px 2px 0 rgba(0, 0, 0, 0.03) !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-3px) !important;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.02) !important;
        border-color: var(--primary-color) !important;
    }
    div[data-testid="stMetricLabel"] > div {
        font-size: 11px !important;
        color: var(--text-color) !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.075em !important;
        opacity: 0.7 !important;
    }
    div[data-testid="stMetricValue"] > div {
        font-size: 26px !important;
        color: var(--text-color) !important;
        font-weight: 800 !important;
        font-family: 'Outfit', sans-serif !important;
    }

    /* Premium Segmented Tabs */
    .stTabs [data-baseweb="tab-list"] {
        background-color: var(--secondary-background-color) !important;
        border-radius: 12px !important;
        padding: 6px !important;
        gap: 6px !important;
        border-bottom: none !important;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 8px 16px !important;
        color: var(--text-color) !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        font-size: 0.875rem !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
        opacity: 0.7 !important;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background-color: rgba(128, 128, 128, 0.1) !important;
        opacity: 1.0 !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: var(--background-color) !important;
        color: var(--primary-color) !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03) !important;
        opacity: 1.0 !important;
    }
    .stTabs [data-baseweb="tab-highlight-list"] {
        display: none !important;
    }

    /* Status Pill Badges */
    .status-badge {
        padding: 6px 12px;
        border-radius: 9999px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        display: inline-block;
        letter-spacing: 0.05em;
    }
    .badge-flagged {
        background-color: rgba(217, 119, 6, 0.15) !important;
        color: #d97706 !important;
        border: 1px solid rgba(217, 119, 6, 0.3) !important;
    }
    .badge-posted {
        background-color: rgba(21, 128, 61, 0.15) !important;
        color: #15803d !important;
        border: 1px solid rgba(21, 128, 61, 0.3) !important;
    }
    .badge-failed {
        background-color: rgba(185, 28, 28, 0.15) !important;
        color: #b91c1c !important;
        border: 1px solid rgba(185, 28, 28, 0.3) !important;
    }

    /* Button Animations */
    .stButton > button {
        border-radius: 10px !important;
        padding: 8px 16px !important;
        font-weight: 600 !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.06) !important;
    }
    .stButton > button:active {
        transform: translateY(0) !important;
    }

    /* Expander Card Styling */
    div[data-testid="stExpander"] {
        border: 1px solid rgba(128, 128, 128, 0.2) !important;
        border-radius: 12px !important;
        background-color: var(--background-color) !important;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05) !important;
        margin-bottom: 12px !important;
        overflow: hidden;
    }
    div[data-testid="stExpander"] details {
        border: none !important;
    }
    div[data-testid="stExpander"] summary {
        font-weight: 600 !important;
        color: var(--text-color) !important;
        padding: 12px 16px !important;
    }
    div[data-testid="stExpander"] summary:hover {
        background-color: var(--secondary-background-color) !important;
    }

    /* File Uploader Border Accent */
    div[data-testid="stFileUploader"] {
        border: 2px dashed rgba(128, 128, 128, 0.3) !important;
        border-radius: 12px !important;
        padding: 12px !important;
        background-color: var(--secondary-background-color) !important;
        transition: border-color 0.2s ease !important;
    }
    div[data-testid="stFileUploader"]:hover {
        border-color: var(--primary-color) !important;
    }

    /* Sidebar Clean styling */
    section[data-testid="stSidebar"] {
        border-right: 1px solid rgba(128, 128, 128, 0.15) !important;
    }
    </style>
""", unsafe_allow_html=True)

API_BASE_URL = "http://127.0.0.1:8000/api/v1"

# Session State Initialization
# --- MAIN INTERFACE RENDERER ---
def render_dashboard(company, token):
    
    # Core Panel Header
    st.markdown(f"<h1 class='outfit-font'>Smart Accounting Module 📊</h1>", unsafe_allow_html=True)
    st.markdown(f"Manage data pipelines for **{company.name}** (Zoho ID: `{company.zoho_org_id}`).")
    st.markdown("---")

    # Main Tabs
    tab1, tab2, tab3 = st.tabs([
        "📁 Upload & Asynchronous Stepper",
        "⚠️ Pending Approvals Panel",
        "📜 Audit Trails & Logs"
    ])

    # Tab 1: Upload Documents (Asynchronous Polling Stepper)
    with tab1:
        st.markdown("<h3 class='outfit-font'>Upload Statement Documents</h3>", unsafe_allow_html=True)
        st.write("Upload PDF bank statements or Excel sheets.")
        
        uploaded_files = st.file_uploader(
            "Select financial files to ingest",
            type=["pdf", "xlsx", "xls"],
            accept_multiple_files=True
        )
        
        if uploaded_files:
            auto_clean = st.checkbox("⚡ Auto-Clean & Force Auto-Post (Bypass Manual Review queue)", value=False)
            if st.button("Trigger Asynchronous Job 🚀"):
                # Prepare form data
                files_payload = []
                for f in uploaded_files:
                    files_payload.append(
                        ("files", (f.name, f.getvalue(), f.type))
                    )
                
                headers = {"Authorization": f"Bearer {token}"}
                data = {"company_id": company.id}
                
                with st.spinner("Submitting pipeline job to background workers..."):
                    try:
                        auto_clean_param = "true" if auto_clean else "false"
                        # Call upload with sync=false
                        res = requests.post(
                            f"{API_BASE_URL}/upload?sync=false&auto_clean={auto_clean_param}",
                            headers=headers,
                            data=data,
                            files=files_payload
                        )
                        
                        if res.status_code == 200:
                            job_data = res.json()
                            job_id = job_data["id"]
                            st.info(f"Job successfully queued! ID: `{job_id}`")
                            
                            # Start polling job progress bar
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            while True:
                                job_res = requests.get(f"{API_BASE_URL}/jobs/{job_id}", headers=headers)
                                if job_res.status_code == 200:
                                    job_status = job_res.json()
                                    status = job_status["status"]
                                    processed = job_status["processed_rows"]
                                    total = job_status["total_rows"]
                                    
                                    # Update UI
                                    status_text.markdown(f"**Job Status:** `{status.upper()}` | **Progress:** `{processed}` of `{total}` rows processed.")
                                    if total > 0:
                                        progress_bar.progress(min(1.0, float(processed) / float(total)))
                                    
                                    if status in ["completed", "failed"]:
                                        if status == "completed":
                                            st.success(f"Job completed! Processed {total} rows of transactions.")
                                            
                                            # Fetch and display details of what was posted
                                            results_res = requests.get(f"{API_BASE_URL}/jobs/{job_id}/results", headers=headers)
                                            if results_res.status_code == 200:
                                                results_data = results_res.json()
                                                if results_data:
                                                    posted_items = [r for r in results_data if r["status"] == "posted"]
                                                    flagged_items = [r for r in results_data if r["status"] == "flagged"]
                                                    failed_items = [r for r in results_data if r["status"] == "failed"]
                                                    
                                                    st.markdown("### 📊 Ingestion Job Summary")
                                                    
                                                    # Display metrics
                                                    col_p, col_fl, col_fa, col_sum = st.columns(4)
                                                    with col_p:
                                                        st.metric("Posted to Zoho", len(posted_items))
                                                    with col_fl:
                                                        st.metric("Flagged for Review", len(flagged_items))
                                                    with col_fa:
                                                        st.metric("Failed", len(failed_items))
                                                    with col_sum:
                                                        total_posted_amt = sum(r["amount"] for r in posted_items)
                                                        st.metric("Total Posted", f"AED {total_posted_amt:,.2f}")
                                                        
                                                    # Display posted items table
                                                    if posted_items:
                                                        st.markdown("#### ✅ Successfully Posted Transactions")
                                                        rows_list = []
                                                        for r in posted_items:
                                                            desc = r["zoho_fields"].get("description", "") if r["zoho_fields"] else ""
                                                            if not desc:
                                                                desc = r["zoho_fields"].get("supplier_name", "") if r["zoho_fields"] else ""
                                                            if not desc:
                                                                desc = r["zoho_fields"].get("customer_name", "") if r["zoho_fields"] else ""
                                                            
                                                            rows_list.append({
                                                                "Row": r["row_number"],
                                                                "File": r["source_file"],
                                                                "Module": r["zoho_module"].upper(),
                                                                "Amount": f"AED {r['amount']:,.2f}",
                                                                "Zoho ID": r["zoho_record_id"],
                                                                "Details/Merchant": desc
                                                            })
                                                        df_posted = pd.DataFrame(rows_list)
                                                        st.dataframe(df_posted, use_container_width=True, hide_index=True)
                                                        
                                                    # Display flagged/failed details
                                                    if flagged_items:
                                                        st.markdown("#### ⚠️ Flagged/Pending Review")
                                                        for r in flagged_items:
                                                            st.warning(f"Row {r['row_number']} in {r['source_file']} | Amount: AED {r['amount']:,.2f} | Reason: {r['flag_reason']}")
                                                            
                                                    if failed_items:
                                                        st.markdown("#### ❌ Failed Postings")
                                                        for r in failed_items:
                                                            st.error(f"Row {r['row_number']} in {r['source_file']} | Amount: AED {r['amount']:,.2f} | Error: {r['flag_reason']}")
                                        else:
                                            st.error(f"Job processing failed: {job_status.get('error_message')}")
                                        break
                                else:
                                    st.error("Lost connection to background job tracker")
                                    break
                                time.sleep(1.5)
                                
                            st.button("Dismiss & Ingest More Files 🔄")
                        else:
                            st.error(f"Submission failed: {res.json().get('detail', res.text)}")
                    except Exception as e:
                        st.error(f"Connection failed: {e}")

    # Tab 2: Manual Approvals Panel (Chart of Accounts sync dropdowns)
    with tab2:
        st.markdown("<h3 class='outfit-font'>Manual Ingestion Review</h3>", unsafe_allow_html=True)
        st.write("Modify mapped categories and banks from synced Zoho Books list before posting.")

        # Fetch flagged logs from the API
        flagged_entries = []
        headers = {"Authorization": f"Bearer {token}"}
        try:
            res_flagged = requests.get(f"{API_BASE_URL}/companies/{company.id}/flagged", headers=headers)
            if res_flagged.status_code == 200:
                flagged_entries = [DotDict(item) for item in res_flagged.json()]
            else:
                st.error("Failed to fetch flagged review queue from API.")
        except Exception as e:
            st.error(f"API connection failed: {e}")

        if not flagged_entries:
            st.success("🎉 No pending transactions! Everything is fully classified and posted.")
        else:
            # Sync Zoho Books Chart of Accounts and Bank Accounts
            headers = {"Authorization": f"Bearer {token}"}
            
            with st.spinner("Syncing Zoho Books accounts..."):
                try:
                    # Sync Chart of Accounts
                    coa_res = requests.get(f"{API_BASE_URL}/companies/{company.id}/accounts", headers=headers)
                    if coa_res.status_code == 200:
                        coa_list = coa_res.json()
                        coa_names = [a["account_name"] for a in coa_list]
                    else:
                        coa_names = ["Office Supplies", "Software Expense", "Travel Expenses", "Meals and Entertainment", "Other Expenses"]
                        
                    # Sync Bank/Cash Accounts
                    bank_res = requests.get(f"{API_BASE_URL}/companies/{company.id}/bank-accounts", headers=headers)
                    if bank_res.status_code == 200:
                        bank_list = bank_res.json()
                        bank_names = [b["account_name"] for b in bank_list]
                    else:
                        bank_names = ["WIO Bank", "Mashreq Bank", "Standard Chartered Bank", "Petty Cash"]
                except Exception as e:
                    coa_names = ["Office Supplies", "Software Expense", "Travel Expenses", "Meals and Entertainment", "Other Expenses"]
                    bank_names = ["WIO Bank", "Mashreq Bank", "Standard Chartered Bank", "Petty Cash"]

            col_info, col_clear = st.columns([3, 1])
            with col_info:
                st.info(f"Showing {len(flagged_entries)} transactions requiring verification.")
            with col_clear:
                if st.button("Clear All Pending 🗑️", use_container_width=True):
                    headers = {"Authorization": f"Bearer {token}"}
                    try:
                        res = requests.post(
                            f"{API_BASE_URL}/companies/{company.id}/clear-flagged",
                            headers=headers
                        )
                        if res.status_code == 200:
                            st.success("Cleared all pending approvals!")
                            time.sleep(1.0)
                            st.rerun()
                        else:
                            st.error(f"Failed to clear: {res.json().get('detail', res.text)}")
                    except Exception as e:
                        st.error(f"Error: {e}")

            for idx, entry in enumerate(flagged_entries):
                with st.expander(
                    f"AED {entry.amount:,.2f} | File: {entry.source_file} | Row: {entry.row_number} | Flagged: {entry.flag_reason}"
                ):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**AI Inferred Data / Original Content:**")
                        st.json(entry.raw_data or {})
                        
                    with col2:
                        st.markdown("**Verify Zoho Mapping:**")
                        zoho_fields = entry.zoho_fields or {}
                        
                        # Form fields
                        date_val = st.text_input("Date", value=zoho_fields.get("date", ""), key=f"date_{entry.id}")
                        amount_val = st.number_input("Amount", value=float(zoho_fields.get("amount", entry.amount)), key=f"amount_{entry.id}")
                        desc_val = st.text_area("Description", value=zoho_fields.get("description", ""), key=f"desc_{entry.id}")
                        
                        # Dynamic selectors populated from Zoho Books Chart of Accounts
                        default_acc = zoho_fields.get("account_name", "Other Expenses")
                        if default_acc not in coa_names:
                            coa_names = [default_acc] + coa_names
                        account_name_val = st.selectbox("Expense Category", options=coa_names, index=coa_names.index(default_acc), key=f"acc_{entry.id}")
                        
                        default_bank = zoho_fields.get("paid_through_account", "WIO Bank")
                        if default_bank not in bank_names:
                            bank_names = [default_bank] + bank_names
                        paid_through_val = st.selectbox("Paid Through Account", options=bank_names, index=bank_names.index(default_bank), key=f"bank_{entry.id}")

                        overrides = {
                            "date": date_val,
                            "amount": amount_val,
                            "description": desc_val,
                            "account_name": account_name_val,
                            "paid_through_account": paid_through_val
                        }
                        
                        if st.button(f"Approve & Post to Zoho ✅", key=f"btn_{entry.id}"):
                            headers = {
                                "X-Session-Token": f"session_{company.id}",  # matches company session token requirement
                                "Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"
                            }
                            payload = {"overrides": overrides}
                            
                            with st.spinner("Posting to Zoho Books..."):
                                try:
                                    res = requests.post(
                                        f"{API_BASE_URL}/approve/{entry.id}",
                                        headers=headers,
                                        json=payload
                                    )
                                    
                                    if res.status_code == 200:
                                        res_data = res.json()
                                        st.success(f"Success! Zoho Record ID: {res_data.get('zoho_record_id')}")
                                        time.sleep(1.0)
                                        st.rerun()
                                    else:
                                        st.error(f"Approval failed: {res.json().get('detail', res.text)}")
                                except Exception as e:
                                    st.error(f"API Error: {e}")

    # Tab 3: Audit Trails & Log History (Auditing and tracking)
    with tab3:
        st.markdown("<h3 class='outfit-font'>Audit Log History</h3>", unsafe_allow_html=True)
        st.write("Verifiable logging trail of all pipeline uploads, user logins, and transaction approvals.")
        
        headers = {"Authorization": f"Bearer {token}"}
        try:
            res = requests.get(f"{API_BASE_URL}/companies/{company.id}/audit-logs", headers=headers)
            if res.status_code == 200:
                logs_data = res.json()
                if logs_data:
                    df_logs = pd.DataFrame(logs_data)
                    # Format created_at nicely
                    df_logs["created_at"] = pd.to_datetime(df_logs["created_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")
                    df_logs.columns = ["Log ID", "Operator Email", "Operation Action", "Details / Summary", "IP Address", "Timestamp (UTC)"]
                    st.dataframe(df_logs, use_container_width=True, hide_index=True)
                else:
                    st.info("No audit logs found for this company.")
            else:
                st.error("Failed to query audit trail.")
        except Exception as e:
            st.error(f"Failed to connect to API: {e}")


# --- MAIN CONTROL ROUTER ---

st.sidebar.markdown("<h2 class='outfit-font'>Smart Ingest 💸</h2>", unsafe_allow_html=True)

# Register New Company Form
CURRENCY_OPTIONS = [
    "AED - UAE Dirham",
    "AFN - Afghan Afghani",
    "ALL - Albanian Lek",
    "AMD - Armenian Dram",
    "ANG - Netherlands Antillean Guilder",
    "AOA - Angolan Kwanza",
    "ARS - Argentine Peso",
    "AUD - Australian Dollar",
    "AWG - Aruban Florin",
    "AZN - Azerbaijani Manat",
    "BAM - Bosnia-Herzegovina Convertible Mark",
    "BBD - Barbadian Dollar",
    "BDT - Bangladeshi Taka",
    "BGN - Bulgarian Lev",
    "BHD - Bahraini Dinar",
    "BIF - Burundian Franc",
    "BMD - Bermudian Dollar",
    "BND - Brunei Dollar",
    "BOB - Bolivian Boliviano",
    "BRL - Brazilian Real",
    "BSD - Bahamian Dollar",
    "BTN - Bhutanese Ngultrum",
    "BWP - Botswanan Pula",
    "BYN - Belarusian Ruble",
    "BZD - Belize Dollar",
    "CAD - Canadian Dollar",
    "CDF - Congolese Franc",
    "CHF - Swiss Franc",
    "CLP - Chilean Peso",
    "CNY - Chinese Yuan",
    "COP - Colombian Peso",
    "CRC - Costa Rican Colón",
    "CUP - Cuban Peso",
    "CVE - Cape Verdean Escudo",
    "CZK - Czech Koruna",
    "DJF - Djiboutian Franc",
    "DKK - Danish Krone",
    "DOP - Dominican Peso",
    "DZD - Algerian Dinar",
    "EGP - Egyptian Pound",
    "ERN - Eritrean Nakfa",
    "ETB - Ethiopian Birr",
    "EUR - Euro",
    "FJD - Fijian Dollar",
    "FKP - Falkland Islands Pound",
    "GBP - British Pound",
    "GEL - Georgian Lari",
    "GHS - Ghanaian Cedi",
    "GIP - Gibraltar Pound",
    "GMD - Gambian Dalasi",
    "GNF - Guinean Franc",
    "GTQ - Guatemalan Quetzal",
    "GYD - Guyanaese Dollar",
    "HKD - Hong Kong Dollar",
    "HNL - Honduran Lempira",
    "HRK - Croatian Kuna",
    "HTG - Haitian Gourde",
    "HUF - Hungarian Forint",
    "IDR - Indonesian Rupiah",
    "ILS - Israeli New Shekel",
    "INR - Indian Rupee",
    "IQD - Iraqi Dinar",
    "IRR - Iranian Rial",
    "ISK - Icelandic Króna",
    "JMD - Jamaican Dollar",
    "JOD - Jordanian Dinar",
    "JPY - Japanese Yen",
    "KES - Kenyan Shilling",
    "KGS - Kyrgyzstani Som",
    "KHR - Cambodian Riel",
    "KMF - Comorian Franc",
    "KPW - North Korean Won",
    "KRW - South Korean Won",
    "KWD - Kuwaiti Dinar",
    "KYD - Cayman Islands Dollar",
    "KZT - Kazakhstani Tenge",
    "LAK - Laotian Kip",
    "LBP - Lebanese Pound",
    "LKR - Sri Lankan Rupee",
    "LRD - Liberian Dollar",
    "LSL - Lesotho Loti",
    "LYD - Libyan Dinar",
    "MAD - Moroccan Dirham",
    "MDL - Moldovan Leu",
    "MGA - Malagasy Ariary",
    "MKD - Macedonian Denar",
    "MMK - Myanmar Kyat",
    "MNT - Mongolian Tugrik",
    "MOP - Macanese Pataca",
    "MRU - Mauritanian Ouguiya",
    "MUR - Mauritian Rupee",
    "MVR - Maldivian Rufiyaa",
    "MWK - Malawian Kwacha",
    "MXN - Mexican Peso",
    "MYR - Malaysian Ringgit",
    "MZN - Mozambican Metical",
    "NAD - Namibian Dollar",
    "NGN - Nigerian Naira",
    "NIO - Nicaraguan Córdoba",
    "NOK - Norwegian Krone",
    "NPR - Nepalese Rupee",
    "NZD - New Zealand Dollar",
    "OMR - Omani Rial",
    "PAB - Panamanian Balboa",
    "PEN - Peruvian Sol",
    "PGK - Papua New Guinean Kina",
    "PHP - Philippine Peso",
    "PKR - Pakistani Rupee",
    "PLN - Polish Zloty",
    "PYG - Paraguayan Guarani",
    "QAR - Qatari Riyal",
    "RON - Romanian Leu",
    "RSD - Serbian Dinar",
    "RUB - Russian Ruble",
    "RWF - Rwandan Franc",
    "SAR - Saudi Riyal",
    "SBD - Solomon Islands Dollar",
    "SCR - Seychellois Rupee",
    "SDG - Sudanese Pound",
    "SEK - Swedish Krona",
    "SGD - Singapore Dollar",
    "SHP - St. Helena Pound",
    "SLL - Sierra Leonean Leone",
    "SOS - Somali Shilling",
    "SRD - Surinamese Dollar",
    "SSP - South Sudanese Pound",
    "STN - São Tomé & Príncipe Dobra",
    "SVC - Salvadoran Colón",
    "SYP - Syrian Pound",
    "SZL - Swazi Lilangeni",
    "THB - Thai Baht",
    "TJS - Tajikistani Somoni",
    "TMT - Turkmenistani Manat",
    "TND - Tunisian Dinar",
    "TOP - Tongan Paʻanga",
    "TRY - Turkish Lira",
    "TTD - Trinidad & Tobago Dollar",
    "TWD - New Taiwan Dollar",
    "TZS - Tanzanian Shilling",
    "UAH - Ukrainian Hryvnia",
    "UGX - Ugandan Shilling",
    "USD - US Dollar",
    "UYU - Uruguayan Peso",
    "UZS - Uzbekistani Som",
    "VES - Venezuelan Bolívar",
    "VND - Vietnamese Dong",
    "VUV - Vanuatu Vatu",
    "WST - Samoan Tala",
    "XAF - Central African CFA Franc",
    "XCD - East Caribbean Dollar",
    "XOF - West African CFA Franc",
    "XPF - CFP Franc",
    "YER - Yemeni Rial",
    "ZAR - South African Rand",
    "ZMW - Zambian Kwacha",
    "ZWL - Zimbabwean Dollar"
]

with st.sidebar.expander("Register New Company 🏢", expanded=False):
    reg_name = st.text_input("Company Name")
    reg_org_id = st.text_input("Zoho Books Org ID")
    reg_currency = st.selectbox("Base Currency", CURRENCY_OPTIONS)
    if st.button("Register & Connect", use_container_width=True):
        if reg_name and reg_org_id:
            selected_currency = reg_currency.split(" - ")[0]
            payload = {
                "name": reg_name,
                "zoho_org_id": reg_org_id,
                "currency_code": selected_currency
            }
            try:
                res_register = requests.post(f"{API_BASE_URL}/add-company", json=payload)
                if res_register.status_code == 201:
                    st.sidebar.success(f"Registered {reg_name}!")
                    time.sleep(1.0)
                    st.rerun()
                else:
                    detail = res_register.json().get("detail", "Registration failed")
                    st.sidebar.error(detail)
            except Exception as e:
                st.sidebar.error(f"Failed to connect to API: {e}")
        else:
            st.sidebar.warning("All fields are required")

# Retrieve companies list from API
companies = []
try:
    res_companies = requests.get(f"{API_BASE_URL}/companies")
    if res_companies.status_code == 200:
        companies = [DotDict(c) for c in res_companies.json()]
    else:
        st.sidebar.error("Failed to load companies from API.")
except Exception as e:
    st.sidebar.error(f"Failed to connect to API: {e}")

if not companies:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.info("No companies registered yet. Please register a company first using the sidebar form.")
    with col2:
        st.markdown("<h1 class='outfit-font' style='margin-top: 40px;'>Smart Accounting Hub 💸</h1>", unsafe_allow_html=True)
        st.markdown("### Production-Grade Ingestion and Posting System")
        st.write("Welcome to the Smart Accounting SaaS module. Please register a company profile in the sidebar to configure data pipelines, process statements, and review manual ledger mappings.")
        
        # Display aesthetic features card
        st.markdown("""
        <div class='glass-card'>
            <h4 class='outfit-font'>Platform Features</h4>
            <ul>
                <li><b>Asynchronous Processing Tasks</b>: Prevents request timeouts on large sheets.</li>
                <li><b>AI Classification Engine</b>: Automatically analyzes and classifies ledger items using Claude.</li>
                <li><b>Secure Sync</b>: Real-time dynamic sync with Zoho Books Chart of Accounts.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
else:
    company_names = [c.name for c in companies]
    selected_name = st.sidebar.selectbox("Select Active Company", options=company_names)
    active_company = next(c for c in companies if c.name == selected_name)
    
    # Zoho connection status block
    st.sidebar.markdown("---")
    st.sidebar.markdown("<h3 class='outfit-font'>Zoho Connection</h3>", unsafe_allow_html=True)
    
    token = f"session_{active_company.id}"
    
    if active_company.zoho_connected:
        st.sidebar.success(f"Connected to Zoho Books\nOrg ID: {active_company.zoho_org_id}")
    else:
        st.sidebar.warning("Not connected to Zoho Books")
        if st.sidebar.button("Generate OAuth Link 🔗", use_container_width=True):
            headers = {"Authorization": f"Bearer {token}"}
            try:
                res = requests.get(f"{API_BASE_URL}/connect-zoho?company_id={active_company.id}", headers=headers)
                if res.status_code == 200:
                    auth_url = res.json().get("authorization_url")
                    st.sidebar.markdown(f"[Authorize App in Zoho]({auth_url})")
                else:
                    st.sidebar.error(f"Error: {res.json().get('detail')}")
            except Exception as e:
                st.sidebar.error(f"Failed to generate link: {e}")

    # Render dashboard
    render_dashboard(active_company, token)
