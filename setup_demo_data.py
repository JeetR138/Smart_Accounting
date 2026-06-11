import os
import pandas as pd
from datetime import datetime, timedelta
from smart_accounting.app.database import engine, SessionLocal, Base
from smart_accounting.app.models import Company, ZohoToken

def setup_demo():
    # 1. Initialize SQLite Database tables
    print("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Check if company already exists
        company = db.query(Company).filter(Company.zoho_org_id == "ORG_UP").first()
        if not company:
            print("Registering demo company: Upload Test Co...")
            company = Company(name="Upload Test Co", zoho_org_id="ORG_UP", zoho_connected=True)
            db.add(company)
            db.commit()
            db.refresh(company)
        else:
            print(f"Demo company already exists with ID: {company.id}")

        # Check if Zoho token exists
        token = db.query(ZohoToken).filter(ZohoToken.company_id == company.id).first()
        if not token:
            print("Creating mock Zoho token for demo company...")
            token = ZohoToken(
                company_id=company.id,
                access_token="mock_access_token_value",
                refresh_token="mock_refresh_token_value",
                expires_at=datetime.utcnow() + timedelta(hours=1)
            )
            db.add(token)
            db.commit()
        else:
            # Refresh expiry
            token.expires_at = datetime.utcnow() + timedelta(hours=1)
            db.commit()
            print("Refreshed mock Zoho token expiry.")
            
        print(f"\nDemo Setup Complete!")
        print(f"Company ID: {company.id}")
        print(f"Use Header: X-Session-Token: session_{company.id}")
        
    finally:
        db.close()

def create_demo_excel():
    excel_path = "expenses.xlsx"
    print(f"Generating demo Excel file: {excel_path}...")
    df = pd.DataFrame([
        ["2026-06-10", "Amazon Web Services", "Hosting", 450.00],
        ["2026-06-10", "Google Workspace", "Software", 60.00],
        ["2026-06-10", "Client Dinner", "Meals", 15000.00]  # high amount, will be flagged
    ], columns=["Expense Date", "Merchant", "Category", "Amount"])
    
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Expenses", index=False)
    print("Demo Excel file generated successfully.")

if __name__ == "__main__":
    setup_demo()
    create_demo_excel()
