from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class FlaggedEntryResponse(BaseModel):
    id: int
    company_id: int
    source_file: str
    row_number: int
    zoho_module: str
    amount: float
    status: str
    flag_reason: Optional[str] = None
    zoho_fields: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class UploadSummary(BaseModel):
    total_rows: int
    posted: int
    flagged: int
    failed: int


class UploadResponse(BaseModel):
    summary: UploadSummary
    flagged_entries: List[FlaggedEntryResponse]


class ApproveRequest(BaseModel):
    overrides: Optional[Dict[str, Any]] = None


class ApproveResponse(BaseModel):
    entry_id: int
    status: str
    zoho_record_id: str
    posted_at: datetime


class JobResponse(BaseModel):
    id: str
    company_id: int
    status: str
    total_rows: int
    processed_rows: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
