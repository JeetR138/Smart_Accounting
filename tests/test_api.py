import os
import io
import pytest
import tempfile
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set testing environment variable
os.environ["TESTING"] = "True"

from smart_accounting.app.main import app
from smart_accounting.app.database import Base, get_db
from smart_accounting.app.models import Company, ZohoToken, ProcessingLog

# Create temp file path for test database
TEST_DB_FILE = os.path.join(tempfile.gettempdir(), "smart_accounting_test.db")
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"

# Test database setup
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(autouse=True)
def setup_database():
    # Dispose active connections before removing
    engine.dispose()
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except:
            pass
            
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    
    # Teardown: dispose and delete db file
    engine.dispose()
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except:
            pass


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_companies_auth_blocking():
    # Calling list companies without session token should return 401
    response = client.get("/api/v1/companies")
    assert response.status_code == 422  # Header parameter validation failure
    
    response = client.get("/api/v1/companies", headers={"X-Session-Token": ""})
    assert response.status_code == 401


def test_add_company_and_list():
    headers = {"X-Session-Token": "super_admin_session"}
    
    # Add company
    payload = {"name": "CRM Integrated Co", "zoho_org_id": "ORG555666"}
    response = client.post("/api/v1/add-company", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json()["name"] == "CRM Integrated Co"
    
    # List companies
    response = client.get("/api/v1/companies", headers=headers)
    assert response.status_code == 200
    companies = response.json()
    assert len(companies) == 1
    assert companies[0]["zoho_org_id"] == "ORG555666"


def test_tenant_isolation_connect_zoho():
    headers = {"X-Session-Token": "super_admin_session"}
    
    # Add company 1
    client.post("/api/v1/add-company", json={"name": "Company One", "zoho_org_id": "ORG1"}, headers=headers)
    # Add company 2
    client.post("/api/v1/add-company", json={"name": "Company Two", "zoho_org_id": "ORG2"}, headers=headers)
    
    # 1. Accessing company 1 with session_1 token -> Should pass
    response = client.get("/api/v1/connect-zoho?company_id=1", headers={"X-Session-Token": "session_1"})
    assert response.status_code == 200
    assert "authorization_url" in response.json()
    
    # 2. Accessing company 2 with session_1 token -> Should fail (403 Forbidden)
    response = client.get("/api/v1/connect-zoho?company_id=2", headers={"X-Session-Token": "session_1"})
    assert response.status_code == 403
    assert "Unauthorized" in response.json()["detail"]


def test_upload_documents_workflow():
    # 1. Setup company and tokens first
    db = TestingSessionLocal()
    company = Company(name="Upload Test Co", zoho_org_id="ORG_UP", zoho_connected=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    token = ZohoToken(company_id=company.id, access_token="mock_token", refresh_token="mock_refresh", expires_at=pd.Timestamp.now() + pd.Timedelta(hours=1))
    db.add(token)
    db.commit()
    
    # Extract IDs before closing session to avoid DetachedInstanceError
    company_id = company.id
    db.close()
    
    # 2. Prepare mock Excel file in memory
    excel_buffer = io.BytesIO()
    df = pd.DataFrame([
        ["2026-12-10", "Amazon Web Services", "Hosting", 450.00],
        ["2026-12-11", "Client Lunch", "Meals", 15000.00]  # high amount, will be flagged
    ], columns=["Expense Date", "Merchant", "Category", "Amount"])
    
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Expenses", index=False)
    excel_buffer.seek(0)
    
    # 3. Call upload
    response = client.post(
        "/api/v1/upload",
        data={"company_id": company_id},
        files=[("files", ("expenses.xlsx", excel_buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        headers={"X-Session-Token": f"session_{company_id}"}
    )
    
    assert response.status_code == 200
    res_data = response.json()
    # Verify summary: 1 posted (high confidence AWS), 1 flagged (client lunch high amount)
    assert res_data["summary"]["total_rows"] == 2
    assert res_data["summary"]["posted"] == 1
    assert res_data["summary"]["flagged"] == 1
    
    # Verify flagged entries detail
    assert len(res_data["flagged_entries"]) == 1
    flagged_item = res_data["flagged_entries"][0]
    assert flagged_item["amount"] == 15000.00
    assert flagged_item["status"] == "flagged"
    assert "high petty cash" in flagged_item["flag_reason"].lower() or "value" in flagged_item["flag_reason"].lower()


def test_approve_flagged_entry_workflow():
    # 1. Setup company, tokens, and a flagged entry
    db = TestingSessionLocal()
    company = Company(name="Approve Test Co", zoho_org_id="ORG_APP", zoho_connected=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    token = ZohoToken(company_id=company.id, access_token="mock_token", refresh_token="mock_refresh", expires_at=pd.Timestamp.now() + pd.Timedelta(hours=1))
    db.add(token)
    
    flagged_log = ProcessingLog(
        company_id=company.id,
        source_file="expenses.xlsx",
        row_number=1,
        zoho_module="expenses",
        amount=15000.00,
        status="flagged",
        flag_reason="High petty cash value",
        zoho_fields={"date": "2026-12-11", "amount": 15000.00, "description": "Client Lunch"}
    )
    db.add(flagged_log)
    db.commit()
    db.refresh(flagged_log)
    
    # Extract scalar IDs before closing session
    company_id = company.id
    entry_id = flagged_log.id
    db.close()
    
    # 2. Block approval call if session token is missing or unauthorized (cross-tenant check)
    response = client.post(
        f"/api/v1/approve/{entry_id}",
        json={"overrides": {"account_name": "Meals and Entertainment"}},
        headers={"X-Session-Token": "session_999"}  # non-matching session token
    )
    assert response.status_code == 403
    
    # 3. Approve with valid session
    response = client.post(
        f"/api/v1/approve/{entry_id}",
        json={"overrides": {"account_name": "Meals and Entertainment", "paid_through_account": "WIO Bank"}},
        headers={"X-Session-Token": f"session_{company_id}"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "posted"
    assert response.json()["zoho_record_id"].startswith("mock_zoho_expenses_")
    
    # Check DB update
    db = TestingSessionLocal()
    updated_log = db.query(ProcessingLog).filter(ProcessingLog.id == entry_id).first()
    assert updated_log.status == "posted"
    assert updated_log.zoho_fields["account_name"] == "Meals and Entertainment"
    db.close()


def test_upload_invalid_magic_bytes_blocked():
    # 1. Setup company first
    db = TestingSessionLocal()
    company = Company(name="Security Co", zoho_org_id="ORG_SEC1", zoho_connected=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    token = ZohoToken(company_id=company.id, access_token="mock_token", refresh_token="mock_refresh", expires_at=pd.Timestamp.now() + pd.Timedelta(hours=1))
    db.add(token)
    db.commit()
    company_id = company.id
    db.close()

    # Attempt to upload a python script named statement.pdf
    script_content = b"import os\nprint('Disguised script payload')"
    file_payload = io.BytesIO(script_content)
    
    response = client.post(
        "/api/v1/upload",
        data={"company_id": company_id},
        files=[("files", ("statement.pdf", file_payload, "application/pdf"))],
        headers={"X-Session-Token": f"session_{company_id}"}
    )
    # Rejects because it has .pdf extension but starts with b"import os" (not PDF_MAGIC "%PDF-")
    assert response.status_code == 400
    assert "validation failed" in response.json()["detail"]


def test_upload_oversized_file_blocked():
    # 1. Setup company first
    db = TestingSessionLocal()
    company = Company(name="Security Co 2", zoho_org_id="ORG_SEC2", zoho_connected=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    token = ZohoToken(company_id=company.id, access_token="mock_token", refresh_token="mock_refresh", expires_at=pd.Timestamp.now() + pd.Timedelta(hours=1))
    db.add(token)
    db.commit()
    company_id = company.id
    db.close()

    # Attempt to upload a file larger than 10MB
    large_pdf_content = b"%PDF-" + b"0" * (11 * 1024 * 1024)
    file_payload = io.BytesIO(large_pdf_content)
    
    response = client.post(
        "/api/v1/upload",
        data={"company_id": company_id},
        files=[("files", ("statement.pdf", file_payload, "application/pdf"))],
        headers={"X-Session-Token": f"session_{company_id}"}
    )
    # Enforces size limit rejection (HTTP 413 Payload Too Large)
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]
