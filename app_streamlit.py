import streamlit as st
import pandas as pd
import requests
import os
import json
from datetime import datetime
from sqlalchemy.orm import Session
from smart_accounting.app.database import SessionLocal, engine, Base
from smart_accounting.app.models import Company, ZohoToken, ProcessingLog

# Set page config
st.set_page_config(
    page_title="Smart Accounting Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom premium CSS
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
        font-family: 'Inter', sans-serif;
    }
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease-in-out;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .metric-card {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border: 1px solid #e9ecef;
        text-align: center;
    }
    .flagged-card {
        background-color: #fff9db;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #fcc419;
        margin-bottom: 15px;
    }
    .success-card {
        background-color: #ebfbee;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #40c057;
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

API_BASE_URL = "http://127.0.0.1:8000/api/v1"

# Database helper
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Main Title & Subtitle
st.title("Smart Accounting Module 📊")
st.write("Upload PDF/Excel financial records, auto-classify using Claude AI, and review/approve transactions to post to Zoho Books.")
st.markdown("---")

# Initialize Database Session
db = next(get_db())

# SIDEBAR: Company Management & Zoho Connection
st.sidebar.title("Configuration ⚙️")

# Fetch companies
companies = db.query(Company).all()
company_names = {c.name: c for c in companies}

selected_company_name = st.sidebar.selectbox(
    "Select Company",
    options=["-- Select a Company --"] + list(company_names.keys())
)

company = None
if selected_company_name != "-- Select a Company --":
    company = company_names[selected_company_name]
    
    st.sidebar.markdown("### Zoho Books Connection")
    if company.zoho_connected:
        st.sidebar.success(f"Connected to Zoho Books\nOrg ID: {company.zoho_org_id}")
    else:
        st.sidebar.warning("Not connected to Zoho Books")
        if st.sidebar.button("Generate OAuth Link 🔗"):
            session_token = f"session_{company.id}"
            headers = {"X-Session-Token": session_token}
            try:
                res = requests.get(f"{API_BASE_URL}/connect-zoho?company_id={company.id}", headers=headers)
                if res.status_code == 200:
                    auth_url = res.json().get("authorization_url")
                    st.sidebar.markdown(f"[Authorize App in Zoho]({auth_url})")
                else:
                    st.sidebar.error(f"Error: {res.json().get('detail')}")
            except Exception as e:
                st.sidebar.error(f"Failed to call API: {e}")

# Register new company form
with st.sidebar.expander("➕ Register New Company"):
    new_name = st.text_input("Company Name")
    new_org_id = st.text_input("Zoho Org ID")
    if st.button("Register Company"):
        if new_name and new_org_id:
            headers = {"X-Session-Token": "super_admin_session"}
            payload = {"name": new_name, "zoho_org_id": new_org_id}
            try:
                res = requests.post(f"{API_BASE_URL}/add-company", json=payload, headers=headers)
                if res.status_code == 201:
                    st.success(f"Registered {new_name}!")
                    st.rerun()
                else:
                    st.error(res.json().get("detail", "Error registering company"))
            except Exception as e:
                st.error(f"Failed: {e}")
        else:
            st.error("Provide both fields")

# MAIN WORKSPACE
if not company:
    st.info("👈 Please select or register a company in the sidebar to begin.")
else:
    tab1, tab2 = st.tabs(["📁 Upload & Process Documents", "⚠️ Pending Approval Log"])
    
    # TAB 1: UPLOAD AND PROCESS
    with tab1:
        st.subheader("Upload Statements / Spreadsheets")
        st.write("Select one or more PDF bank statements (WIO, Mashreq) or Excel sheets (Network International, NOMOD, Purchases, Expenses, Petty Cash).")
        
        uploaded_files = st.file_uploader(
            "Upload files",
            type=["pdf", "xlsx", "xls"],
            accept_multiple_files=True
        )
        
        if uploaded_files:
            if st.button("Process & Post to Zoho 🚀"):
                # Call backend API
                files_payload = []
                for f in uploaded_files:
                    files_payload.append(
                        ("files", (f.name, f.getvalue(), f.type))
                    )
                
                session_token = f"session_{company.id}"
                headers = {"X-Session-Token": session_token}
                data = {"company_id": company.id}
                
                with st.spinner("Processing documents (parsing, AI classification, posting)..."):
                    try:
                        res = requests.post(
                            f"{API_BASE_URL}/upload",
                            headers=headers,
                            data=data,
                            files=files_payload
                        )
                        
                        if res.status_code == 200:
                            result = res.json()
                            summary = result["summary"]
                            
                            st.success("File processing completed successfully!")
                            
                            # Metrics
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric("Total Rows", summary["total_rows"])
                            with col2:
                                st.metric("Auto-Posted to Zoho", summary["posted"], delta_color="normal")
                            with col3:
                                st.metric("Flagged for Review", summary["flagged"])
                            with col4:
                                st.metric("Failed to Post", summary["failed"])
                                
                            # Flagged entries display
                            flagged = result["flagged_entries"]
                            if flagged:
                                st.warning(f"Flagged {len(flagged)} entries for manual review. Check the 'Pending Approval Log' tab.")
                        else:
                            st.error(f"Upload failed: {res.json().get('detail', res.text)}")
                    except Exception as e:
                        st.error(f"Failed to communicate with API: {e}")
                        
    # TAB 2: PENDING APPROVAL LOG
    with tab2:
        st.subheader("Manual Review & Approval Panel")
        st.write("Below are the transactions flagged with 'low' confidence or containing limits warnings. Modify fields below and approve them to post to Zoho.")
        
        # Query flagged logs for the selected company
        flagged_entries = db.query(ProcessingLog).filter(
            ProcessingLog.company_id == company.id,
            ProcessingLog.status == "flagged"
        ).order_by(ProcessingLog.id.desc()).all()
        
        if not flagged_entries:
            st.success("🎉 No pending flagged entries! All transactions are fully posted.")
        else:
            st.info(f"Showing {len(flagged_entries)} pending transactions requiring approval.")
            
            for idx, entry in enumerate(flagged_entries):
                with st.expander(
                    f"Transaction ID: {entry.id} | Amount: AED {entry.amount:,.2f} | File: {entry.source_file} (Row {entry.row_number})"
                ):
                    st.markdown(f"**⚠️ Flag Reason:** `{entry.flag_reason}`")
                    st.markdown("---")
                    
                    # Columns for review and edit
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**Original Parsed Data:**")
                        st.json(entry.raw_data or {})
                        
                    with col2:
                        st.markdown("**Mapped Zoho Fields (Editable):**")
                        # Default values from AI classification
                        zoho_fields = entry.zoho_fields or {}
                        
                        # Form fields for manual overrides
                        date_val = st.text_input(f"Date ({entry.id})", value=zoho_fields.get("date", ""))
                        amount_val = st.number_input(f"Amount ({entry.id})", value=float(zoho_fields.get("amount", entry.amount)))
                        desc_val = st.text_area(f"Description ({entry.id})", value=zoho_fields.get("description", ""))
                        account_name_val = st.text_input(f"Account Name ({entry.id})", value=zoho_fields.get("account_name", "Office Supplies"))
                        paid_through_val = st.text_input(f"Paid Through Account ({entry.id})", value=zoho_fields.get("paid_through_account", "WIO Bank"))
                        
                        overrides = {
                            "date": date_val,
                            "amount": amount_val,
                            "description": desc_val,
                            "account_name": account_name_val,
                            "paid_through_account": paid_through_val
                        }
                        
                        if st.button(f"Approve & Post to Zoho Books ✅", key=f"btn_{entry.id}"):
                            session_token = f"session_{company.id}"
                            headers = {
                                "X-Session-Token": session_token,
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
                                        st.success(f"Successfully posted! Zoho Record ID: {res_data.get('zoho_record_id')}")
                                        st.rerun()
                                    else:
                                        st.error(f"Approval failed: {res.json().get('detail', res.text)}")
                                except Exception as e:
                                    st.error(f"Connection failed: {e}")
