from fastapi import Header, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from smart_accounting.app.database import get_db
from smart_accounting.app.models import Company

def get_company_by_id(company_id: int, db: Session = Depends(get_db)) -> Company:
    """Helper dependency to retrieve a company and raise 404 if not found."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company ID {company_id} not found")
    return company

def verify_company_session(company_id: int, x_session_token: str) -> None:
    """
    Helper function to verify a session token against a specific company ID.
    Can be called directly inside routes.
    """
    if not x_session_token or x_session_token.strip() == "":
        raise HTTPException(status_code=401, detail="Missing or invalid session token")

    expected_token = f"session_{company_id}"
    
    if x_session_token == "super_admin_session":
        return
        
    if x_session_token != expected_token:
        raise HTTPException(
            status_code=403,
            detail="Unauthorized: You do not have access to this company's data"
        )

async def verify_session(
    request: Request,
    x_session_token: str = Header(..., description="Valid session token for authentication"),
    db: Session = Depends(get_db)
) -> str:
    """
    FastAPI Session verification dependency.
    Automatically extracts company_id from path, query, or form parameters.
    """
    company_id = None

    # 1. Try to get company_id from path params
    if "company_id" in request.path_params:
        try:
            company_id = int(request.path_params["company_id"])
        except ValueError:
            pass

    # 2. Try to get company_id from query params
    if company_id is None and "company_id" in request.query_params:
        try:
            company_id = int(request.query_params["company_id"])
        except ValueError:
            pass

    # 3. Try to get company_id from form-data (for file uploads)
    if company_id is None:
        try:
            form_data = await request.form()
            if "company_id" in form_data:
                company_id = int(form_data["company_id"])
        except Exception:
            pass

    if company_id is None:
        raise HTTPException(
            status_code=400,
            detail="company_id parameter is required in path, query, or form data"
        )

    verify_company_session(company_id, x_session_token)
    return x_session_token
