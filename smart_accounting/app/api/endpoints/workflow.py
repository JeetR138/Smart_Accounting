import os
import shutil
import tempfile
from typing import List
from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from smart_accounting.app.database import get_db
from smart_accounting.app.models import Company, ProcessingLog
from smart_accounting.app.schemas.posting import UploadResponse, ApproveRequest, ApproveResponse, FlaggedEntryResponse
from smart_accounting.app.api.deps import verify_session, verify_company_session, get_company_by_id
from smart_accounting.app.services.parser import parse_document, ParserError
from smart_accounting.app.services.classification import classify_transactions
from smart_accounting.app.services.posting import post_transactions, approve_flagged_entry
from smart_accounting.app.services.security import validate_uploaded_file

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_financial_documents(
    company_id: int = Form(..., description="The ID of the company uploading files"),
    files: List[UploadFile] = File(..., description="Financial statement files (PDF or Excel)"),
    db: Session = Depends(get_db),
    session_token: str = Depends(verify_session)
):
    """
    POST /upload
    Takes company_id and list of files.
    - Validates file format.
    - Parses document lines.
    - Classifies transaction lines using Claude AI.
    - Posts high confidence entries to Zoho Books.
    - Flags low confidence entries for manual approval.
    - Returns execution summary and flagged entries.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    if not company.zoho_connected:
        raise HTTPException(
            status_code=400,
            detail="Company is not connected to Zoho. Please authorize OAuth first."
        )

    all_parsed_rows = []
    
    # Process each uploaded file
    for uploaded_file in files:
        # Perform magic bytes and file size security validations
        validate_uploaded_file(uploaded_file)
        filename = uploaded_file.filename or "uploaded_file"
        ext = os.path.splitext(filename)[1].lower()

        # Write uploaded file content to a temp directory preserving its original filename
        try:
            temp_dir = tempfile.mkdtemp()
            temp_path = os.path.join(temp_dir, filename)
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(uploaded_file.file, buffer)
                
            # Parse rows from file
            parsed_rows = parse_document(temp_path)
            all_parsed_rows.extend(parsed_rows)
            
        except ParserError as pe:
            raise HTTPException(status_code=422, detail=f"Failed parsing {filename}: {pe}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal error processing {filename}: {e}")
        finally:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
            if 'temp_dir' in locals() and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    if not all_parsed_rows:
        return {
            "summary": {"total_rows": 0, "posted": 0, "flagged": 0, "failed": 0},
            "flagged_entries": []
        }

    # Classify the parsed transaction rows using Claude AI (uses mock fallback if API key is mock-key)
    try:
        classified_rows = classify_transactions(all_parsed_rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Classification service failed: {e}")

    # Post high confidence rows to Zoho Books, save others as flagged in log
    stats = post_transactions(db, company_id, company.zoho_org_id, all_parsed_rows, classified_rows)

    # Fetch all flagged entries created during this upload to return to the user
    # For tracking, we query flagged records for this company matching our source files
    source_files = list(set(r["source_file"] for r in all_parsed_rows))
    flagged_db_entries = db.query(ProcessingLog).filter(
        ProcessingLog.company_id == company_id,
        ProcessingLog.status == "flagged",
        ProcessingLog.source_file.in_(source_files)
    ).all()

    return {
        "summary": stats,
        "flagged_entries": flagged_db_entries
    }


@router.post("/approve/{entry_id}", response_model=ApproveResponse)
def approve_transaction_entry(
    entry_id: int,
    payload: ApproveRequest,
    x_session_token: str = Header(..., description="Valid session token"),
    db: Session = Depends(get_db)
):
    """
    POST /approve
    Takes entry ID and optional field corrections, posts transaction to Zoho.
    Verifies that the caller's session token matches the company owning the log entry.
    """
    # 1. Fetch the entry first to find which company owns it
    log_entry = db.query(ProcessingLog).filter(ProcessingLog.id == entry_id).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="Flagged entry not found")

    # 2. Enforce session check for the company owning this entry (prevent cross-tenant leaks)
    verify_company_session(company_id=log_entry.company_id, x_session_token=x_session_token)

    # 3. Post to Zoho Books
    try:
        result = approve_flagged_entry(db, log_entry.company_id, entry_id, overrides=payload.overrides)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
