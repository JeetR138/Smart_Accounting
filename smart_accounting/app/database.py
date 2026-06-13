import os
import sys
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from smart_accounting.app.config import settings

logger = logging.getLogger(__name__)

DATABASE_URL = settings.DATABASE_URL

# Automatically use SQLite in-memory database during tests
if "pytest" in sys.modules or os.getenv("TESTING") == "True":
    DATABASE_URL = "sqlite:///smart_accounting_test.db"

# Create database engine
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

# Create SessionLocal factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for SQLAlchemy models
Base = declarative_base()

def get_db():
    """Dependency for getting DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initializes database tables and runs schema migration checks."""
    Base.metadata.create_all(bind=engine)
    
    # Run dynamic migration check for missing job_id column in processing_log
    db = SessionLocal()
    try:
        db.execute(text("SELECT job_id FROM processing_log LIMIT 1"))
    except Exception:
        # Column doesn't exist, let's add it
        try:
            logger.info("Adding missing job_id column to processing_log table...")
            db.execute(text("ALTER TABLE processing_log ADD COLUMN job_id VARCHAR(36) NULL"))
            db.commit()
            logger.info("Successfully added job_id column to processing_log table.")
        except Exception as alter_err:
            logger.error(f"Failed to add job_id column: {alter_err}")
            db.rollback()
    finally:
        db.close()

    # Run dynamic migration check for missing currency_code column in companies
    db = SessionLocal()
    try:
        db.execute(text("SELECT currency_code FROM companies LIMIT 1"))
    except Exception:
        # Column doesn't exist, let's add it
        try:
            logger.info("Adding missing currency_code column to companies table...")
            db.execute(text("ALTER TABLE companies ADD COLUMN currency_code VARCHAR(3) NOT NULL DEFAULT 'AED'"))
            db.commit()
            logger.info("Successfully added currency_code column to companies table.")
        except Exception as alter_err:
            logger.error(f"Failed to add currency_code column: {alter_err}")
            db.rollback()
    finally:
        db.close()

