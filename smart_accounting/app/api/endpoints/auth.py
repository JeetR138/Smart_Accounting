import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from smart_accounting.app.database import get_db
from smart_accounting.app.models import User, Company, AuditLog
from smart_accounting.app.schemas.user import UserCreate, TokenResponse, UserResponse
from smart_accounting.app.services.security import hash_password, verify_password, create_access_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
def register_user(
    payload: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Registers a new company and user account.
    """
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists"
        )

    # Check if company organization ID already exists
    existing_company = db.query(Company).filter(Company.zoho_org_id == payload.zoho_org_id).first()
    if existing_company:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A company with this Zoho Organization ID already exists"
        )

    try:
        # Create company
        company = Company(
            name=payload.company_name,
            zoho_org_id=payload.zoho_org_id,
            currency_code=payload.currency_code
        )
        db.add(company)
        db.flush()  # Obtain company ID

        # Create user
        hashed_pwd = hash_password(payload.password)
        user = User(
            email=payload.email,
            hashed_password=hashed_pwd,
            role="admin",  # First user of a company is admin
            company_id=company.id
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Log action
        audit = AuditLog(
            company_id=company.id,
            user_id=user.id,
            action="register",
            details={"email": user.email, "company_name": company.name}
        )
        db.add(audit)
        db.commit()

        return user

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to register user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )


@router.post("/token", response_model=TokenResponse)
def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    OAuth2 compatible token login. Validates credentials and returns JWT.
    """
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is not associated with any company"
        )

    # Create token payload containing company_id and role
    token_data = {
        "sub": user.email,
        "user_id": user.id,
        "company_id": user.company_id,
        "role": user.role
    }
    
    access_token = create_access_token(data=token_data)

    # Log action
    ip_addr = request.client.host if request.client else None
    audit = AuditLog(
        company_id=user.company_id,
        user_id=user.id,
        action="login",
        ip_address=ip_addr,
        details={"email": user.email}
    )
    db.add(audit)
    db.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }
