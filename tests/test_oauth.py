import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from smart_accounting.app.database import Base
from smart_accounting.app.models import Company, ZohoToken
from smart_accounting.app.services.oauth import (
    generate_authorization_url,
    exchange_code_for_tokens,
    get_valid_access_token,
    ZohoOAuthError
)

@pytest.fixture
def db_session():
    # Use SQLite in-memory DB for isolated tests
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_generate_authorization_url():
    url = generate_authorization_url(company_id=42)
    assert "scope=ZohoBooks.fullaccess.all" in url
    assert "state=42" in url
    assert "response_type=code" in url


def test_exchange_code_and_get_valid_token(db_session):
    # Setup test company
    company = Company(name="Test Company LLC", zoho_org_id="ORG12345", zoho_connected=False)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    
    # Trade mock code for token (uses mock flow since ZOHO_CLIENT_ID is not configured)
    res = exchange_code_for_tokens(db_session, company.id, "some_mock_code")
    assert res["zoho_connected"] is True
    assert res["access_token"] == "mock_access_token_123"
    
    # Verify company field is updated
    updated_company = db_session.query(Company).filter(Company.id == company.id).first()
    assert updated_company.zoho_connected is True
    
    # Verify token is saved in DB
    token_entry = db_session.query(ZohoToken).filter(ZohoToken.company_id == company.id).first()
    assert token_entry is not None
    assert token_entry.access_token == "mock_access_token_123"
    assert token_entry.refresh_token == "mock_refresh_token_123"
    
    # Fetch valid token (should return existing one without refresh)
    access_token = get_valid_access_token(db_session, company.id)
    assert access_token == "mock_access_token_123"


def test_get_valid_access_token_auto_refresh(db_session):
    company = Company(name="Test Company LLC", zoho_org_id="ORG12345", zoho_connected=True)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    
    # Pre-populate an expired token (expired 10 minutes ago)
    expired_time = datetime.utcnow() - timedelta(minutes=10)
    token_entry = ZohoToken(
        company_id=company.id,
        access_token="old_expired_access_token",
        refresh_token="mock_refresh_token_123",
        expires_at=expired_time
    )
    db_session.add(token_entry)
    db_session.commit()
    
    # Fetching token should trigger auto-refresh
    access_token = get_valid_access_token(db_session, company.id)
    assert access_token != "old_expired_access_token"
    assert access_token.startswith("mock_refreshed_token_")
    
    # Verify token is updated in DB
    updated_token = db_session.query(ZohoToken).filter(ZohoToken.company_id == company.id).first()
    assert updated_token.access_token == access_token
    assert updated_token.expires_at > datetime.utcnow() + timedelta(minutes=50)


def test_get_valid_access_token_unconnected_company(db_session):
    with pytest.raises(ZohoOAuthError) as exc_info:
        get_valid_access_token(db_session, company_id=999)
    assert "no token record found" in str(exc_info.value)
