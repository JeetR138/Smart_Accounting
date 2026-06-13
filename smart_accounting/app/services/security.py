import os
import base64
import hashlib
import bcrypt
from datetime import timedelta
from typing import Optional
from fastapi import HTTPException, UploadFile
from cryptography.fernet import Fernet
from smart_accounting.app.config import settings

def hash_password(password: str) -> str:
    """Hashes a plain text password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain text password against a hashed bcrypt password."""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_fernet() -> Fernet:
    """Derives a secure base64 Fernet key using SHA-256 fallback if the configured key is not standard."""
    key_str = settings.ENCRYPTION_SECRET_KEY
    try:
        # Check if the key is already a valid urlsafe base64 string and 32 bytes long decoded
        key_bytes = base64.urlsafe_b64decode(key_str.encode())
        if len(key_bytes) == 32:
            return Fernet(key_str.encode())
    except Exception:
        pass
    
    # Fallback key derivation from config secret key
    fallback_seed = key_str or settings.SESSION_SECRET_KEY or "fallback-secure-seed-phrase"
    derived_bytes = hashlib.sha256(fallback_seed.encode()).digest()
    derived_key = base64.urlsafe_b64encode(derived_bytes)
    return Fernet(derived_key)

def encrypt_value(value: str) -> str:
    """Encrypts a string using Fernet AES-256."""
    if not value:
        return ""
    fernet = get_fernet()
    return fernet.encrypt(value.encode('utf-8')).decode('utf-8')

def decrypt_value(encrypted_value: str) -> str:
    """Decrypts a Fernet AES-256 encrypted string, with fallback to returning raw input if decryption fails."""
    if not encrypted_value:
        return ""
    fernet = get_fernet()
    try:
        return fernet.decrypt(encrypted_value.encode('utf-8')).decode('utf-8')
    except Exception:
        return encrypted_value

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

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a secure signed JSON Web Token (JWT) using the application settings."""
    import jwt
    from datetime import datetime, timedelta
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
