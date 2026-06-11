from typing import List
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from smart_accounting.app.database import get_db
from smart_accounting.app.models import Company
from smart_accounting.app.schemas.company import CompanyCreate, CompanyResponse
from smart_accounting.app.api.deps import verify_session, get_company_by_id
from smart_accounting.app.services.oauth import generate_authorization_url, exchange_code_for_tokens

router = APIRouter()

def verify_general_session(x_session_token: str = Header(..., description="Valid session token")) -> str:
    """Verifies that the request has a valid session token (general verification)."""
    if not x_session_token or x_session_token.strip() == "":
        raise HTTPException(status_code=401, detail="Missing or invalid session token")
    return x_session_token


@router.get("/companies", response_model=List[CompanyResponse])
def get_companies(
    db: Session = Depends(get_db),
    session: str = Depends(verify_general_session)
):
    """Returns all companies in the system with their Zoho connection status."""
    return db.query(Company).all()


@router.post("/add-company", response_model=CompanyResponse, status_code=201)
def add_company(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    session: str = Depends(verify_general_session)
):
    """Registers a new company with its Zoho organization ID."""
    # Check if unique constraint is violated
    existing = db.query(Company).filter(Company.zoho_org_id == payload.zoho_org_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Company with this Zoho Organization ID already exists")

    company = Company(name=payload.name, zoho_org_id=payload.zoho_org_id)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("/connect-zoho")
def connect_zoho(
    company_id: int = Query(..., description="The ID of the company to connect"),
    db: Session = Depends(get_db),
    session_token: str = Depends(verify_session)
):
    """
    Generates Zoho OAuth authorization URL for the requested company.
    Requires session verification matching the company ID.
    """
    # Verify company exists
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    auth_url = generate_authorization_url(company_id)
    return {"company_id": company_id, "authorization_url": auth_url}


@router.get("/companies/connect-zoho/callback")
def connect_zoho_callback(
    code: str = Query(..., description="The authorization code returned by Zoho"),
    state: str = Query(..., description="The company ID sent in state"),
    db: Session = Depends(get_db)
):
    """
    OAuth 2.0 callback URL.
    Exchanges authorization code for access and refresh tokens.
    """
    try:
        company_id = int(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state parameter (must be company ID)")

    try:
        token_data = exchange_code_for_tokens(db, company_id, code)
        return {
            "status": "success",
            "message": "Zoho Books connected successfully",
            "access_token_preview": f"{token_data['access_token'][:8]}...",
            "expires_at": token_data["expires_at"]
        }
    except Exception as e:
        logger_name = "smart_accounting.app.api.endpoints.companies"
        import logging
        logging.getLogger(logger_name).error(f"Callback token swap failed: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to connect Zoho account: {str(e)}")
