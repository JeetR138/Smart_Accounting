import os
from fastapi import HTTPException, UploadFile

# Security Limits
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB file size limit to prevent oversized file server crashes

# Magic Bytes definitions
PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"  # Modern Excel (.xlsx) is actually a zipped XML package
XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # Legacy Excel (.xls) compound binary format

def validate_uploaded_file(file: UploadFile):
    """
    Validates uploaded file against security guidelines:
    1. Blocks unsupported extensions.
    2. Enforces maximum file size limit (10MB) to prevent oversized file memory/disk exhaustion.
    3. Verifies file content magic bytes (rejects scripts disguised as PDF or Excel).
    """
    filename = file.filename or "uploaded_file"
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in [".pdf", ".xlsx", ".xls"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension for {filename}. Only PDF and Excel are allowed."
        )

    # 1. Enforce size limit
    try:
        # Seek to the end of the file to determine its size
        file.file.seek(0, 2)
        size = file.file.tell()
        # Reset file pointer to the beginning
        file.file.seek(0)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read file size for {filename}: {str(e)}"
        )

    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File {filename} is too large ({size / (1024*1024):.2f} MB). Max allowed size is 10 MB."
        )

    # 2. Enforce magic bytes header checks
    try:
        header_bytes = file.file.read(8)
        # Reset file pointer to the beginning for subsequent readers
        file.file.seek(0)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read file header signature for {filename}: {str(e)}"
        )

    if ext == ".pdf":
        if not header_bytes.startswith(PDF_MAGIC):
            raise HTTPException(
                status_code=400,
                detail=f"File validation failed: {filename} does not have a valid PDF signature."
            )
    elif ext == ".xlsx":
        if not header_bytes.startswith(ZIP_MAGIC):
            raise HTTPException(
                status_code=400,
                detail=f"File validation failed: {filename} does not have a valid Office Open XML signature."
            )
    elif ext == ".xls":
        if not header_bytes.startswith(XLS_MAGIC):
            raise HTTPException(
                status_code=400,
                detail=f"File validation failed: {filename} does not have a valid compound document binary signature."
            )
