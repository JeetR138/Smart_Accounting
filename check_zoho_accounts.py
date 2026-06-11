import httpx
from smart_accounting.app.database import SessionLocal
from smart_accounting.app.services.oauth import get_valid_access_token
from smart_accounting.app.config import settings

def check_accounts():
    db = SessionLocal()
    try:
        company_id = 2
        token = get_valid_access_token(db, company_id)
        
        # Get organization details from DB
        from smart_accounting.app.models import Company
        company = db.query(Company).filter(Company.id == company_id).first()
        org_id = company.zoho_org_id
        
        print(f"Using access token: {token[:8]}...")
        print(f"Using org ID: {org_id}")
        
        # 1. Fetch Chart of Accounts / Bank Accounts
        url = f"{settings.ZOHO_BOOKS_URL}/v3/bankaccounts"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-com-zoho-books-organizationid": org_id
        }
        
        res = httpx.get(url, headers=headers)
        print("\n--- Bank Accounts Response ---")
        print(res.status_code)
        print(res.text)
        
    finally:
        db.close()

if __name__ == "__main__":
    check_accounts()
