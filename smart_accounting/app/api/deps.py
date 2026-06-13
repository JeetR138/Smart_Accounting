import jwt
from fastapi import Header, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from smart_accounting.app.database import get_db
from smart_accounting.app.models import Company, User
from smart_accounting.app.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

def get_company_by_id(company_id: int, db: Session = Depends(get_db)) -> Company:
    """Helper dependency to retrieve a company and raise 404 if not found."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company ID {company_id} not found")
    return company

def verify_company_session(company_id: int, x_session_token: str) -> None:
    """
    Helper function to verify a session token against a specific company ID.
    Supports both legacy and JWT token validation.
    """
    if not x_session_token or x_session_token.strip() == "":
        raise HTTPException(status_code=401, detail="Missing or invalid session token")

    expected_token = f"session_{company_id}"
    
    if x_session_token == "super_admin_session":
        return
        
    if x_session_token != expected_token:
        # If it's a JWT, try to decode and verify company ID
        if not x_session_token.startswith("session_"):
            try:
                payload = jwt.decode(x_session_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
                jwt_company_id = payload.get("company_id")
                if jwt_company_id is not None and int(jwt_company_id) == company_id:
                    return
            except jwt.PyJWTError:
                raise HTTPException(
                    status_code=401,
                    detail="Session token is invalid or expired"
                )
        raise HTTPException(
            status_code=403,
            detail="Unauthorized: You do not have access to this company's data"
        )

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Retrieves the current authenticated user context from the JWT token."""
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Missing Bearer token."
        )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        email: str = payload.get("sub")
        user_id: int = payload.get("user_id")
        if email is None or user_id is None:
            raise HTTPException(status_code=401, detail="Could not validate credentials")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

async def verify_session(
    request: Request,
    db: Session = Depends(get_db)
) -> str:
    """
    FastAPI Session verification dependency.
    Supports both legacy X-Session-Token header AND Authorization Bearer JWT tokens.
    Automatically extracts company_id from path, query, or form parameters.
    """
    company_id = None

    # 1. Extract company_id from path params
    if "company_id" in request.path_params:
        try:
            company_id = int(request.path_params["company_id"])
        except ValueError:
            pass

    # 2. Extract company_id from query params
    if company_id is None and "company_id" in request.query_params:
        try:
            company_id = int(request.query_params["company_id"])
        except ValueError:
            pass

    # 3. Extract company_id from form-data (for file uploads)
    if company_id is None:
        try:
            form_data = await request.form()
            if "company_id" in form_data:
                company_id = int(form_data["company_id"])
        except Exception:
            pass

    # Resolve token from either X-Session-Token or Authorization header
    token = request.headers.get("X-Session-Token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header[7:]

    if not token or token.strip() == "":
        raise HTTPException(status_code=401, detail="Missing or invalid session token")

    # Support super admin bypass
    if token == "super_admin_session":
        return token

    # Check if legacy token is used
    if token.startswith("session_"):
        if company_id is not None:
            verify_company_session(company_id, token)
        return token

    # Verify JWT-based session
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        jwt_company_id = payload.get("company_id")
        if company_id is not None:
            if jwt_company_id is None or int(jwt_company_id) != company_id:
                raise HTTPException(
                    status_code=403,
                    detail="Unauthorized: You do not have access to this company's data"
                )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401,
            detail="Session token is invalid or expired"
        )

    return token
