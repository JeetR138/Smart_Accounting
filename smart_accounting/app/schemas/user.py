from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    email: str
    password: str
    company_name: str
    zoho_org_id: str
    currency_code: str = "AED"


class UserLogin(BaseModel):
    username: str  # OAuth2 password flow uses 'username' for the email field
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    company_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse
