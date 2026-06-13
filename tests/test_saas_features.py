import os
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["TESTING"] = "True"

from smart_accounting.app.main import app
from smart_accounting.app.database import Base, get_db, engine, SessionLocal as TestingSessionLocal
from smart_accounting.app.models import Company, User, Job, AuditLog, ProcessingLog, ZohoToken
from smart_accounting.app.services.security import hash_password, verify_password, encrypt_value, decrypt_value, create_access_token

@pytest.fixture(autouse=True)
def setup_database():
    # Make sure tables are created on the shared engine
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

client = TestClient(app)


def test_password_hashing():
    pwd = "supersecretpassword123"
    hashed = hash_password(pwd)
    assert hashed != pwd
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_token_encryption_decryption():
    secret_token = "secret-zoho-refresh-token-value-xyz"
    encrypted = encrypt_value(secret_token)
    assert encrypted != secret_token
    decrypted = decrypt_value(encrypted)
    assert decrypted == secret_token


def test_registration_and_login_workflow():
    # 1. Register new company and operator
    reg_payload = {
        "email": "operator@mycompany.com",
        "password": "securepassword",
        "company_name": "My Company Inc",
        "zoho_org_id": "ORG999888"
    }
    response = client.post("/api/v1/auth/register", json=reg_payload)
    assert response.status_code == 201
    res_data = response.json()
    assert res_data["email"] == "operator@mycompany.com"
    assert res_data["role"] == "admin"
    assert res_data["company_id"] is not None

    # 2. Log in using OAuth2 password flow format
    login_payload = {
        "username": "operator@mycompany.com",
        "password": "securepassword"
    }
    response = client.post("/api/v1/auth/token", data=login_payload)
    assert response.status_code == 200
    token_data = response.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
    assert token_data["user"]["email"] == "operator@mycompany.com"

    # Verify audit logs was generated
    db = TestingSessionLocal()
    logs = db.query(AuditLog).filter(AuditLog.company_id == res_data["company_id"]).all()
    assert len(logs) >= 2  # registration + login logs
    db.close()


def test_async_job_submission_and_polling():
    # 1. Pre-register company and operator
    db = TestingSessionLocal()
    company = Company(name="Async Test Co", zoho_org_id="ORG_ASYNC", zoho_connected=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    token = ZohoToken(company_id=company.id, access_token="mock_token", refresh_token="mock_refresh", expires_at=datetime.utcnow() + timedelta(hours=1))
    db.add(token)
    db.commit()
    
    hashed_pwd = hash_password("mypassword")
    user = User(email="test@async.com", hashed_password=hashed_pwd, company_id=company.id, role="operator")
    db.add(user)
    db.commit()
    db.refresh(user)
    
    company_id = company.id
    user_id = user.id
    db.close()

    # 2. Get JWT token
    login_response = client.post("/api/v1/auth/token", data={"username": "test@async.com", "password": "mypassword"})
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Create dummy file content starting with valid ZIP magic bytes for .xlsx
    excel_content = b"PK\x03\x04" + b"header1,header2\nval1,val2"
    
    # 4. Trigger async upload (sync=false)
    response = client.post(
        f"/api/v1/upload?sync=false",
        data={"company_id": company_id},
        files=[("files", ("test.xlsx", excel_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        headers=headers
    )
    assert response.status_code == 200
    job_info = response.json()
    assert "id" in job_info
    assert job_info["status"] == "pending"

    # 5. Check job status polling endpoint
    job_id = job_info["id"]
    response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert response.status_code == 200
    polled_job = response.json()
    assert polled_job["id"] == job_id
    assert polled_job["status"] in ["pending", "processing", "completed", "failed"]


def test_dynamic_chart_of_accounts_mock_endpoints():
    db = TestingSessionLocal()
    company = Company(name="CoA Test Co", zoho_org_id="ORG_COA", zoho_connected=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    company_id = company.id  # Save company_id before closing session
    
    token = ZohoToken(company_id=company_id, access_token="mock_token", refresh_token="mock_refresh", expires_at=datetime.utcnow() + timedelta(hours=1))
    db.add(token)
    db.commit()
    
    hashed_pwd = hash_password("mypassword")
    user = User(email="test@coa.com", hashed_password=hashed_pwd, company_id=company_id, role="operator")
    db.add(user)
    db.commit()
    db.close()

    # Get login JWT
    login_response = client.post("/api/v1/auth/token", data={"username": "test@coa.com", "password": "mypassword"})
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Fetch Chart of Accounts List
    response = client.get(f"/api/v1/companies/{company_id}/accounts", headers=headers)
    assert response.status_code == 200
    coa = response.json()
    assert len(coa) > 0
    assert "account_name" in coa[0]

    # 2. Fetch Bank Accounts List
    response = client.get(f"/api/v1/companies/{company_id}/bank-accounts", headers=headers)
    assert response.status_code == 200
    banks = response.json()
    assert len(banks) > 0
    assert "account_name" in banks[0]
