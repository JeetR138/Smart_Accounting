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
from smart_accounting.app.database import Base, get_db, engine, SessionLocal as TestingSessionLocal
from smart_accounting.app.models import Company, ZohoToken, ProcessingLog

@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

# Clear any previous dependency overrides in case of pollution
app.dependency_overrides.clear()
client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_companies_public_endpoints():
    # Calling list companies without session token should return 200 (public route)
    response = client.get("/api/v1/companies")
    assert response.status_code == 200


def test_add_company_and_list():
    # Add company without headers (public route)
    payload = {"name": "CRM Integrated Co", "zoho_org_id": "ORG555666"}
    response = client.post("/api/v1/add-company", json=payload)
    assert response.status_code == 201
    assert response.json()["name"] == "CRM Integrated Co"
    
    # List companies without headers (public route)
    response = client.get("/api/v1/companies")
    assert response.status_code == 200
    companies = response.json()
    assert any(c["name"] == "CRM Integrated Co" for c in companies)
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


def test_clear_flagged_entries_workflow():
    # 1. Setup company, token and flagged entries
    db = TestingSessionLocal()
    company = Company(name="Clear Test Co", zoho_org_id="ORG_CLR", zoho_connected=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    token = ZohoToken(company_id=company.id, access_token="mock_token", refresh_token="mock_refresh", expires_at=pd.Timestamp.now() + pd.Timedelta(hours=1))
    db.add(token)
    
    flagged_log_1 = ProcessingLog(
        company_id=company.id,
        source_file="expenses.xlsx",
        row_number=1,
        zoho_module="expenses",
        amount=100.0,
        status="flagged",
        flag_reason="Vague particulars"
    )
    flagged_log_2 = ProcessingLog(
        company_id=company.id,
        source_file="expenses.xlsx",
        row_number=2,
        zoho_module="expenses",
        amount=200.0,
        status="flagged",
        flag_reason="Vague particulars"
    )
    posted_log = ProcessingLog(
        company_id=company.id,
        source_file="expenses.xlsx",
        row_number=3,
        zoho_module="expenses",
        amount=300.0,
        status="posted"
    )
    db.add(flagged_log_1)
    db.add(flagged_log_2)
    db.add(posted_log)
    db.commit()
    
    company_id = company.id
    db.close()
    
    # 2. Try clearing with invalid token / unauthorized (cross-tenant)
    response = client.post(
        f"/api/v1/companies/{company_id}/clear-flagged",
        headers={"X-Session-Token": "session_999"}
    )
    assert response.status_code == 403
    
    # 3. Clear with valid token
    response = client.post(
        f"/api/v1/companies/{company_id}/clear-flagged",
        headers={"X-Session-Token": f"session_{company_id}"}
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["count"] == 2
    
    # 4. Verify in DB: flagged logs are deleted, posted logs remain
    db = TestingSessionLocal()
    flagged_count = db.query(ProcessingLog).filter(ProcessingLog.company_id == company_id, ProcessingLog.status == "flagged").count()
    posted_count = db.query(ProcessingLog).filter(ProcessingLog.company_id == company_id, ProcessingLog.status == "posted").count()
    db.close()
    
    assert flagged_count == 0
    assert posted_count == 1


def test_upload_documents_auto_clean_workflow():
    # 1. Setup company and tokens
    db = TestingSessionLocal()
    company = Company(name="AutoClean Test Co", zoho_org_id="ORG_AC", zoho_connected=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    token = ZohoToken(company_id=company.id, access_token="mock_token", refresh_token="mock_refresh", expires_at=pd.Timestamp.now() + pd.Timedelta(hours=1))
    db.add(token)
    db.commit()
    
    company_id = company.id
    db.close()
    
    # 2. Prepare mock Excel file in memory (with a high amount that normally gets flagged)
    excel_buffer = io.BytesIO()
    df = pd.DataFrame([
        ["2026-12-10", "Amazon Web Services", "Hosting", 450.00],
        ["2026-12-11", "Client Lunch", "Meals", 15000.00]  # high amount, would normally be flagged
    ], columns=["Expense Date", "Merchant", "Category", "Amount"])
    
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Expenses", index=False)
    excel_buffer.seek(0)
    
    # 3. Call upload with auto_clean=True (sync=True)
    response = client.post(
        "/api/v1/upload?auto_clean=true",
        data={"company_id": company_id},
        files=[("files", ("expenses.xlsx", excel_buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        headers={"X-Session-Token": f"session_{company_id}"}
    )
    
    assert response.status_code == 200
    res_data = response.json()
    # Verify summary: both should be posted directly! 0 flagged!
    assert res_data["summary"]["total_rows"] == 2
    assert res_data["summary"]["posted"] == 2
    assert res_data["summary"]["flagged"] == 0
    assert len(res_data["flagged_entries"]) == 0
    
    # Verify in DB: both entries have status "posted"
    db = TestingSessionLocal()
    logs = db.query(ProcessingLog).filter(ProcessingLog.company_id == company_id).all()
    assert len(logs) == 2
    assert logs[0].status == "posted"
    assert logs[1].status == "posted"
    db.close()


def test_job_results_endpoint():
    # 1. Setup company, tokens, a job, and processing logs linked to that job
    db = TestingSessionLocal()
    company = Company(name="Job Results Test Co", zoho_org_id="ORG_JR", zoho_connected=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    token = ZohoToken(company_id=company.id, access_token="mock_token", refresh_token="mock_refresh", expires_at=pd.Timestamp.now() + pd.Timedelta(hours=1))
    db.add(token)
    
    from smart_accounting.app.models import Job
    job = Job(id="test-job-uuid-123", company_id=company.id, status="completed", total_rows=2, processed_rows=2)
    db.add(job)
    
    log1 = ProcessingLog(
        company_id=company.id,
        source_file="expenses.xlsx",
        row_number=1,
        zoho_module="expenses",
        amount=100.0,
        status="posted",
        zoho_record_id="mock_zoho_rec_1",
        job_id="test-job-uuid-123"
    )
    log2 = ProcessingLog(
        company_id=company.id,
        source_file="expenses.xlsx",
        row_number=2,
        zoho_module="expenses",
        amount=200.0,
        status="flagged",
        flag_reason="Vague details",
        job_id="test-job-uuid-123"
    )
    db.add(log1)
    db.add(log2)
    db.commit()
    
    company_id = company.id
    db.close()
    
    # 2. Access with invalid session token -> should fail
    response = client.get(
        "/api/v1/jobs/test-job-uuid-123/results",
        headers={"X-Session-Token": "session_999"}
    )
    assert response.status_code == 403
    
    # 3. Access with valid session token -> should succeed
    response = client.get(
        "/api/v1/jobs/test-job-uuid-123/results",
        headers={"X-Session-Token": f"session_{company_id}"}
    )
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 2
    assert res_data[0]["zoho_record_id"] == "mock_zoho_rec_1"
    assert res_data[1]["status"] == "flagged"
    assert res_data[1]["flag_reason"] == "Vague details"


def test_get_flagged_entries_api():
    from smart_accounting.app.models import ProcessingLog, Company, ZohoToken
    from datetime import datetime, timedelta
    
    db = TestingSessionLocal()
    company = Company(name="Flagged API Test Co", zoho_org_id="ORG_FL_API", zoho_connected=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    token = ZohoToken(company_id=company.id, access_token="mock_token", refresh_token="mock_refresh", expires_at=datetime.utcnow() + timedelta(hours=1))
    db.add(token)
    db.commit()

    log = ProcessingLog(
        company_id=company.id,
        source_file="statement.xlsx",
        row_number=1,
        amount=1200.0,
        status="flagged",
        flag_reason="Needs approval",
        zoho_module="expenses"
    )
    db.add(log)
    db.commit()
    
    response = client.get(
        f"/api/v1/companies/{company.id}/flagged",
        headers={"X-Session-Token": f"session_{company.id}"}
    )
    assert response.status_code == 200
    res_data = response.json()
    assert len(res_data) == 1
    assert res_data[0]["amount"] == 1200.0
    assert res_data[0]["status"] == "flagged"
    
    db.delete(log)
    db.delete(token)
    db.delete(company)
    db.commit()
    db.close()




