from datetime import datetime
from pydantic import BaseModel


class CompanyBase(BaseModel):
    name: str
    zoho_org_id: str


class CompanyCreate(CompanyBase):
    pass


class CompanyResponse(CompanyBase):
    id: int
    zoho_connected: bool
    created_at: datetime

    class Config:
        from_attributes = True
