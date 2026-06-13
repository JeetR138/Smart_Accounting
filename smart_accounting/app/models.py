from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Numeric, JSON
from sqlalchemy.orm import relationship
from smart_accounting.app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    zoho_org_id = Column(String(50), nullable=False, unique=True)
    zoho_connected = Column(Boolean, default=False)
    currency_code = Column(String(3), nullable=False, default="AED")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    token = relationship("ZohoToken", back_populates="company", uselist=False, cascade="all, delete-orphan")
    logs = relationship("ProcessingLog", back_populates="company", cascade="all, delete-orphan")
    users = relationship("User", back_populates="company", cascade="all, delete-orphan")


class ZohoToken(Base):
    __tablename__ = "zoho_tokens"

    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    access_token = Column(String(2048), nullable=False)  # Increased length to store encrypted tokens
    refresh_token = Column(String(2048), nullable=False)  # Increased length to store encrypted tokens
    expires_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="token")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="operator")  # e.g., 'admin', 'operator'
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="users")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, index=True)  # UUID string
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), nullable=False, default="pending")  # pending, processing, completed, failed
    total_rows = Column(Integer, default=0)
    processed_rows = Column(Integer, default=0)
    error_message = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    company = relationship("Company")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(100), nullable=False)  # e.g., 'register', 'login', 'upload', 'approve', 'connect_zoho'
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProcessingLog(Base):
    __tablename__ = "processing_log"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    source_file = Column(String(255), nullable=False)
    row_number = Column(Integer, nullable=False)
    zoho_record_id = Column(String(100), nullable=True)
    zoho_module = Column(String(50), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(20), nullable=False)  # e.g., 'posted', 'flagged', 'failed'
    posted_at = Column(DateTime, nullable=True)
    
    # Enrichment fields for manual review and debug
    flag_reason = Column(String(255), nullable=True)
    zoho_fields = Column(JSON, nullable=True)           # Mapped/corrected fields
    original_zoho_fields = Column(JSON, nullable=True)  # AI-generated fields before edits
    raw_data = Column(JSON, nullable=True)              # Raw dictionary from parser
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    company = relationship("Company", back_populates="logs")
