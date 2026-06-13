import os
import shutil
import tempfile
import uuid
import logging
import jwt
import httpx
from datetime import datetime
from typing import List, Dict, Any, Union, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File, Form, Query, BackgroundTasks
from sqlalchemy.orm import Session

from smart_accounting.app.database import get_db, SessionLocal
from smart_accounting.app.models import Company, ProcessingLog, Job, AuditLog, User
from smart_accounting.app.schemas.posting import UploadResponse, ApproveRequest, ApproveResponse, FlaggedEntryResponse, JobResponse
from smart_accounting.app.api.deps import verify_session, verify_company_session, get_company_by_id
from smart_accounting.app.services.parser import parse_document, ParserError
from smart_accounting.app.services.classification import classify_transactions
from smart_accounting.app.services.posting import post_transactions, approve_flagged_entry
from smart_accounting.app.services.security import validate_uploaded_file
from smart_accounting.app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def get_user_id_from_token(token: str) -> Optional[int]:
    """Decodes token to find user_id. Returns None for legacy/test tokens."""
    if not token or token.startswith("session_") or token == "super_admin_session":
        return None
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("user_id")
    except Exception:
        return None


def process_uploaded_documents_task(
    job_id: str,
    company_id: int,
    file_paths: List[str],
    auto_clean: bool = False
):
    """
    Background worker task to parse, classify, and post transactions.
    """
    db = SessionLocal()
    try:
        # 1. Update job status to processing
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Background job {job_id} not found in DB")
            return
        
        job.status = "processing"
        db.commit()

        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise ValueError(f"Company ID {company_id} not found")

        # 2. Parse all files
        all_parsed_rows = []
        for path in file_paths:
            try:
                parsed = parse_document(path, default_currency=company.currency_code)
                all_parsed_rows.extend(parsed)
            except Exception as pe:
                logger.error(f"Background parsing failed for {os.path.basename(path)}: {pe}")
                raise pe
            finally:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

        if not all_parsed_rows:
            job.status = "completed"
            job.error_message = "No transaction data found in files"
            db.commit()
            return

        # Update Job total_rows
        job.total_rows = len(all_parsed_rows)
        job.status = "classifying"
        db.commit()

        # 3. Classify transactions using Claude
        try:
            classified_rows = classify_transactions(all_parsed_rows)
        except Exception as ce:
            logger.error(f"Background AI Classification failed: {ce}")
            raise ce

        # 4. Post transactions to Zoho Books
        job.status = "posting"
        db.commit()

        stats = post_transactions(
            db=db,
            company_id=company_id,
            zoho_org_id=company.zoho_org_id,
            parsed_rows=all_parsed_rows,
            classified_rows=classified_rows,
            job_id=job_id,
            auto_clean=auto_clean
        )

        # 5. Mark job completed
        job.status = "completed"
        job.processed_rows = len(all_parsed_rows)
        db.commit()

    except Exception as e:
        logger.error(f"Background job {job_id} failed: {e}")
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(e)
            db.commit()
    finally:
        db.close()


@router.post("/upload", response_model=Union[UploadResponse, JobResponse])
async def upload_financial_documents(
    background_tasks: BackgroundTasks,
    company_id: int = Form(..., description="The ID of the company uploading files"),
    files: List[UploadFile] = File(..., description="Financial statement files (PDF or Excel)"),
    sync: bool = Query(True, description="Whether to run synchronously (default True for testing)"),
    auto_clean: bool = Query(False, description="Whether to automatically force high confidence and bypass review"),
    db: Session = Depends(get_db),
    session_token: str = Depends(verify_session)
):
    """
    POST /upload
    Takes company_id and list of files. Supports synchronous (sync=True) and asynchronous (sync=False) processing.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    if not company.zoho_connected:
        raise HTTPException(
            status_code=400,
            detail="Company is not connected to Zoho. Please authorize OAuth first."
        )

    # Validate and copy all files to temporary directory
    temp_paths = []
    temp_dir = tempfile.mkdtemp()
    
    try:
        for uploaded_file in files:
            validate_uploaded_file(uploaded_file)
            filename = uploaded_file.filename or "uploaded_file"
            temp_path = os.path.join(temp_dir, filename)
            
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(uploaded_file.file, buffer)
            temp_paths.append(temp_path)
    except HTTPException:
        # clean up temp dir on validation failure
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise
    except Exception as e:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise HTTPException(status_code=500, detail=f"Failed to upload files: {str(e)}")

    user_id = get_user_id_from_token(session_token)

    # A. Synchronous Flow (Legacy / Testing fallback)
    if sync:
        all_parsed_rows = []
        try:
            for path in temp_paths:
                parsed_rows = parse_document(path, default_currency=company.currency_code)
                all_parsed_rows.extend(parsed_rows)
        except ParserError as pe:
            raise HTTPException(status_code=422, detail=f"Failed parsing document: {pe}")
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

        if not all_parsed_rows:
            return {
                "summary": {"total_rows": 0, "posted": 0, "flagged": 0, "failed": 0},
                "flagged_entries": []
            }

        try:
            classified_rows = classify_transactions(all_parsed_rows)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI Classification service failed: {e}")

        stats = post_transactions(db, company_id, company.zoho_org_id, all_parsed_rows, classified_rows, auto_clean=auto_clean)

        # Log audit log
        audit = AuditLog(
            company_id=company_id,
            user_id=user_id,
            action="upload_sync",
            details={"files": [f.filename for f in files], "summary": stats}
        )
        db.add(audit)
        db.commit()

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

    # B. Asynchronous Flow (Production standard)
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        company_id=company_id,
        status="pending",
        total_rows=0,
        processed_rows=0
    )
    db.add(job)
    
    # Audit log entry
    audit = AuditLog(
        company_id=company_id,
        user_id=user_id,
        action="upload_async_submit",
        details={"job_id": job_id, "files": [f.filename for f in files]}
    )
    db.add(audit)
    db.commit()
    db.refresh(job)

    # Schedule background task to run parsing, classification and posting
    background_tasks.add_task(
        process_uploaded_documents_task,
        job_id=job_id,
        company_id=company_id,
        file_paths=temp_paths,
        auto_clean=auto_clean
    )

    return job


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    session_token: str = Depends(verify_session)
):
    """
    Retrieves the status, total rows, and processed rows of an upload job.
    Enforces tenant isolation by matching user session to job company.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # Enforce tenant check
    verify_company_session(company_id=job.company_id, x_session_token=session_token)
    
    return job


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

    user_id = get_user_id_from_token(x_session_token)

    # 3. Post to Zoho Books
    try:
        result = approve_flagged_entry(db, log_entry.company_id, entry_id, overrides=payload.overrides)
        
        # Update approved_by operator ID
        if user_id:
            log_entry.approved_by = user_id
            db.commit()

        # Log audit entry
        audit = AuditLog(
            company_id=log_entry.company_id,
            user_id=user_id,
            action="approve_transaction",
            details={
                "entry_id": entry_id,
                "amount": float(log_entry.amount),
                "zoho_record_id": result.get("zoho_record_id"),
                "overrides": payload.overrides
            }
        )
        db.add(audit)
        db.commit()

        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{company_id}/accounts")
def list_zoho_accounts(
    company_id: int,
    db: Session = Depends(get_db),
    session_token: str = Depends(verify_session)
):
    """
    Returns cached Chart of Accounts list for mapping expense categories.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
        
    if not company.zoho_connected:
        raise HTTPException(status_code=400, detail="Company is not connected to Zoho")

    try:
        from smart_accounting.app.services.oauth import get_valid_access_token
        from smart_accounting.app.services.posting import get_cached_accounts
        access_token = get_valid_access_token(db, company_id)
        accounts = get_cached_accounts(access_token, company.zoho_org_id)
        
        expense_accounts = [a for a in accounts if a.get("account_type") in ["expense", "cost_of_goods_sold"]]
        if not expense_accounts:
            expense_accounts = accounts
        return expense_accounts
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch accounts from Zoho: {str(e)}")


@router.get("/companies/{company_id}/bank-accounts")
def list_zoho_bank_accounts(
    company_id: int,
    db: Session = Depends(get_db),
    session_token: str = Depends(verify_session)
):
    """
    Returns bank/cash accounts list from Zoho for mapping paid-through sources.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
        
    if not company.zoho_connected:
        raise HTTPException(status_code=400, detail="Company is not connected to Zoho")

    try:
        from smart_accounting.app.services.oauth import get_valid_access_token
        access_token = get_valid_access_token(db, company_id)
        
        url = f"{settings.ZOHO_BOOKS_URL}/v3/bankaccounts?organization_id={company.zoho_org_id}"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        if not settings.ZOHO_CLIENT_ID or settings.ZOHO_CLIENT_ID == "your-zoho-client-id" or access_token.startswith("mock_"):
            return [
                {"account_id": "mock_bank_account_id_WIO_Bank", "account_name": "WIO Bank"},
                {"account_id": "mock_bank_account_id_Mashreq_Bank", "account_name": "Mashreq Bank"},
                {"account_id": "mock_bank_account_id_Standard_Chartered_Bank", "account_name": "Standard Chartered Bank"},
                {"account_id": "mock_bank_account_id_Petty_Cash", "account_name": "Petty Cash"}
            ]
            
        res = httpx.get(url, headers=headers)
        if res.status_code == 200:
            res_json = res.json()
            if res_json.get("code") == 0:
                return [
                    {"account_id": a.get("account_id"), "account_name": a.get("account_name")}
                    for a in res_json.get("bankaccounts", [])
                ]
        raise ValueError(f"Zoho returned code: {res.status_code}, msg: {res.text}")
    except Exception as e:
        logger.error(f"Failed to fetch bank accounts: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch bank accounts from Zoho: {str(e)}")


@router.get("/companies/{company_id}/audit-logs")
def list_company_audit_logs(
    company_id: int,
    db: Session = Depends(get_db),
    session_token: str = Depends(verify_session)
):
    """
    Retrieves the system operation audit logs for tracking.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    logs = db.query(AuditLog).filter(AuditLog.company_id == company_id).order_by(AuditLog.created_at.desc()).all()
    
    # Enrich logs with user email if available
    results = []
    for log in logs:
        user_email = "System/Test Token"
        if log.user_id:
            user = db.query(User).filter(User.id == log.user_id).first()
            if user:
                user_email = user.email
        results.append({
            "id": log.id,
            "user_email": user_email,
            "action": log.action,
            "details": log.details,
            "ip_address": log.ip_address,
            "created_at": log.created_at
        })
    return results


@router.post("/companies/{company_id}/clear-flagged")
def clear_flagged_entries(
    company_id: int,
    db: Session = Depends(get_db),
    session_token: str = Depends(verify_session)
):
    """
    Clears (deletes) all flagged processing log entries for the company.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
        
    verify_company_session(company_id=company_id, x_session_token=session_token)
    
    user_id = get_user_id_from_token(session_token)
    
    # Delete flagged logs
    deleted_count = db.query(ProcessingLog).filter(
        ProcessingLog.company_id == company_id,
        ProcessingLog.status == "flagged"
    ).delete(synchronize_session=False)
    
    # Log audit entry
    audit = AuditLog(
        company_id=company_id,
        user_id=user_id,
        action="clear_flagged",
        details={"deleted_count": deleted_count}
    )
    db.add(audit)
    db.commit()
    
    return {"message": "Successfully cleared all pending approvals", "count": deleted_count}


@router.get("/jobs/{job_id}/results")
def get_job_results(
    job_id: str,
    db: Session = Depends(get_db),
    session_token: str = Depends(verify_session)
):
    """
    Retrieves all processing logs associated with a specific upload job.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    verify_company_session(company_id=job.company_id, x_session_token=session_token)
    
    logs = db.query(ProcessingLog).filter(ProcessingLog.job_id == job_id).order_by(ProcessingLog.row_number).all()
    
    return [
        {
            "row_number": log.row_number,
            "source_file": log.source_file,
            "zoho_record_id": log.zoho_record_id,
            "zoho_module": log.zoho_module,
            "amount": float(log.amount),
            "status": log.status,
            "flag_reason": log.flag_reason,
            "zoho_fields": log.zoho_fields
        }
        for log in logs
    ]


@router.get("/companies/{company_id}/flagged", response_model=List[FlaggedEntryResponse])
def get_flagged_entries(
    company_id: int,
    db: Session = Depends(get_db),
    session_token: str = Depends(verify_session)
):
    """
    Retrieves all processing logs flagged for manual review for a specific company.
    """
    company = get_company_by_id(company_id, db)
    verify_company_session(company_id=company_id, x_session_token=session_token)
    
    entries = db.query(ProcessingLog).filter(
        ProcessingLog.company_id == company_id,
        ProcessingLog.status == "flagged"
    ).order_by(ProcessingLog.id.desc()).all()
    
    return entries



