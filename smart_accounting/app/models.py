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
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    token = relationship("ZohoToken", back_populates="company", uselist=False, cascade="all, delete-orphan")
    logs = relationship("ProcessingLog", back_populates="company", cascade="all, delete-orphan")


class ZohoToken(Base):
    __tablename__ = "zoho_tokens"

    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    access_token = Column(String(1024), nullable=False)
    refresh_token = Column(String(512), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="token")


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
    zoho_fields = Column(JSON, nullable=True)  # Contains mapped API fields from Claude
    raw_data = Column(JSON, nullable=True)     # Raw dictionary from parser

    # Relationships
    company = relationship("Company", back_populates="logs")
