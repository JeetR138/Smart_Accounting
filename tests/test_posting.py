import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock

from smart_accounting.app.database import Base
from smart_accounting.app.models import Company, ZohoToken, ProcessingLog
from smart_accounting.app.services.posting import (
    post_transactions,
    approve_flagged_entry,
    ZohoAPIError,
    ZohoRateLimitError,
    _execute_zoho_post,
    get_or_create_zoho_bank_account
)

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def setup_company(db_session):
    company = Company(name="Post Test LLC", zoho_org_id="ORG999", zoho_connected=True)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    
    token = ZohoToken(
        company_id=company.id,
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at=datetime.utcnow() + timedelta(hours=1)
    )
    db_session.add(token)
    db_session.commit()
    return company


def test_post_transactions_mixed_confidence(db_session, setup_company):
    # 1 high confidence, 1 low confidence
    parsed_rows = [
        {"date": "2026-12-10", "description": "Payment to Supplier A", "amount": 1500.00, "type": "debit", "source_file": "purchases.xlsx"},
        {"date": "2026-12-11", "description": "Ambiguous Cash Entry", "amount": 25000.00, "type": "debit", "source_file": "petty_cash.xlsx"}
    ]
    classified_rows = [
        {
            "zoho_module": "bills",
            "zoho_fields": {"date": "2026-12-10", "amount": 1500.00, "supplier_name": "Supplier A", "description": "Payment to Supplier A"},
            "confidence": "high",
            "flag_reason": ""
        },
        {
            "zoho_module": "expenses",
            "zoho_fields": {"date": "2026-12-11", "amount": 25000.00, "description": "Ambiguous Cash Entry"},
            "confidence": "low",
            "flag_reason": "High petty cash expense value"
        }
    ]
    
    stats = post_transactions(db_session, setup_company.id, setup_company.zoho_org_id, parsed_rows, classified_rows)
    
    assert stats["total_rows"] == 2
    assert stats["posted"] == 1
    assert stats["flagged"] == 1
    assert stats["failed"] == 0
    
    # Check log database entries
    logs = db_session.query(ProcessingLog).filter(ProcessingLog.company_id == setup_company.id).order_by(ProcessingLog.row_number).all()
    assert len(logs) == 2
    
    # Row 1 posted
    assert logs[0].status == "posted"
    assert logs[0].zoho_module == "bills"
    assert logs[0].amount == 1500.00
    assert logs[0].zoho_record_id.startswith("mock_zoho_bills_")
    assert logs[0].flag_reason is None
    
    # Row 2 flagged
    assert logs[1].status == "flagged"
    assert logs[1].zoho_module == "expenses"
    assert logs[1].amount == 25000.00
    assert logs[1].zoho_record_id is None
    assert logs[1].flag_reason == "High petty cash expense value"


def test_approve_flagged_entry_success(db_session, setup_company):
    # Setup a flagged entry in the log
    log_entry = ProcessingLog(
        company_id=setup_company.id,
        source_file="petty_cash.xlsx",
        row_number=1,
        zoho_module="expenses",
        amount=150.00,
        status="flagged",
        flag_reason="Vague particulars details",
        zoho_fields={"date": "2026-12-12", "amount": 150.00, "description": "Vague particulars details"}
    )
    db_session.add(log_entry)
    db_session.commit()
    db_session.refresh(log_entry)
    
    # Approve and apply overrides
    overrides = {"account_name": "Office Supplies", "paid_through_account": "Petty Cash"}
    res = approve_flagged_entry(db_session, setup_company.id, log_entry.id, overrides=overrides)
    
    assert res["status"] == "posted"
    assert res["zoho_record_id"].startswith("mock_zoho_expenses_")
    
    # Check database was updated
    updated_log = db_session.query(ProcessingLog).filter(ProcessingLog.id == log_entry.id).first()
    assert updated_log.status == "posted"
    assert updated_log.zoho_fields["account_name"] == "Office Supplies"
    assert updated_log.zoho_fields["paid_through_account"] == "Petty Cash"
    assert updated_log.flag_reason is None


@patch("httpx.post")
def test_rate_limiting_retry(mock_post):
    # Configure mock responses: 429 once, then 200 success
    mock_response_429 = MagicMock()
    mock_response_429.status_code = 429
    
    mock_response_200 = MagicMock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {
        "code": 0,
        "message": "success",
        "expense": {"expense_id": "zoho_exp_456"}
    }
    
    # Set side effect
    mock_post.side_effect = [mock_response_429, mock_response_200]
    
    # Force use of real HTTP request flow (via non-mock settings variables)
    with patch("smart_accounting.app.services.posting.settings") as mock_settings:
        mock_settings.ZOHO_CLIENT_ID = "real-client-id"
        mock_settings.ZOHO_BOOKS_URL = "https://zohoapis.com/books"
        
        record_id = _execute_zoho_post("real_access_token", "ORG999", "expenses", {"amount": 100})
        
        assert record_id == "zoho_exp_456"
        assert mock_post.call_count == 2


@patch("httpx.get")
def test_get_or_create_zoho_bank_account_caching(mock_get):
    # Setup mock response for bank account list
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "code": 0,
        "bankaccounts": [
            {"account_id": "acc_111", "account_name": "WIO Bank"}
        ]
    }
    mock_get.return_value = mock_res
    
    with patch("smart_accounting.app.services.posting.settings") as mock_settings:
        mock_settings.ZOHO_CLIENT_ID = "real-client-id"
        mock_settings.ZOHO_BOOKS_URL = "https://zohoapis.com/books"
        
        # Clear cache first to isolate the test
        from smart_accounting.app.services.posting import _bank_accounts_cache
        _bank_accounts_cache.clear()
        
        # Call it twice
        id1 = get_or_create_zoho_bank_account("real_token", "ORG999", "wio_statement")
        id2 = get_or_create_zoho_bank_account("real_token", "ORG999", "wio_statement")
        
        assert id1 == "acc_111"
        assert id2 == "acc_111"
        # httpx.get should be called only once due to cache
        assert mock_get.call_count == 1


@patch("smart_accounting.app.services.posting.post_row_to_zoho")
def test_post_transactions_abort_on_rate_limit(mock_post_row, db_session, setup_company):
    # Mock post_row_to_zoho to raise daily rate limit error on first row
    mock_post_row.side_effect = ZohoAPIError("Zoho API daily rate limit exceeded: limit reached")
    
    parsed_rows = [
        {"date": "2026-12-10", "description": "Row 1", "amount": 100.0, "type": "debit", "source_file": "purchases.xlsx"},
        {"date": "2026-12-11", "description": "Row 2", "amount": 200.0, "type": "debit", "source_file": "purchases.xlsx"},
        {"date": "2026-12-12", "description": "Row 3", "amount": 300.0, "type": "debit", "source_file": "purchases.xlsx"}
    ]
    classified_rows = [
        {"zoho_module": "expenses", "zoho_fields": {}, "confidence": "high", "flag_reason": ""},
        {"zoho_module": "expenses", "zoho_fields": {}, "confidence": "high", "flag_reason": ""},
        {"zoho_module": "expenses", "zoho_fields": {}, "confidence": "high", "flag_reason": ""}
    ]
    
    stats = post_transactions(db_session, setup_company.id, setup_company.zoho_org_id, parsed_rows, classified_rows)
    
    assert stats["total_rows"] == 3
    assert stats["posted"] == 0
    # First one fails, subsequent ones are skipped/failed due to abort
    assert stats["failed"] == 3
    assert mock_post_row.call_count == 1
    
    logs = db_session.query(ProcessingLog).filter(ProcessingLog.company_id == setup_company.id).order_by(ProcessingLog.row_number).all()
    assert logs[0].flag_reason == "Posting failed: Zoho API daily rate limit exceeded: limit reached"
    assert logs[1].flag_reason == "Posting skipped: Zoho API daily rate limit exceeded"
    assert logs[2].flag_reason == "Posting skipped: Zoho API daily rate limit exceeded"


@patch("smart_accounting.app.services.posting.post_row_to_zoho")
def test_post_transactions_abort_on_auth_error(mock_post_row, db_session, setup_company):
    # Mock post_row_to_zoho to raise authentication failure error
    mock_post_row.side_effect = ZohoAPIError("Zoho API error: Authentication failed (code: 57)")
    
    parsed_rows = [
        {"date": "2026-12-10", "description": "Row 1", "amount": 100.0, "type": "debit", "source_file": "purchases.xlsx"},
        {"date": "2026-12-11", "description": "Row 2", "amount": 200.0, "type": "debit", "source_file": "purchases.xlsx"}
    ]
    classified_rows = [
        {"zoho_module": "expenses", "zoho_fields": {}, "confidence": "high", "flag_reason": ""},
        {"zoho_module": "expenses", "zoho_fields": {}, "confidence": "high", "flag_reason": ""}
    ]
    
    stats = post_transactions(db_session, setup_company.id, setup_company.zoho_org_id, parsed_rows, classified_rows)
    
    assert stats["total_rows"] == 2
    assert stats["failed"] == 2
    assert mock_post_row.call_count == 1
    
    logs = db_session.query(ProcessingLog).filter(ProcessingLog.company_id == setup_company.id).order_by(ProcessingLog.row_number).all()
    assert logs[0].flag_reason == "Posting failed: Zoho API error: Authentication failed (code: 57)"
    assert logs[1].flag_reason == "Posting skipped: Zoho authentication failed or token expired"
