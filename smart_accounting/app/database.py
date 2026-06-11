import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from smart_accounting.app.config import settings

DATABASE_URL = settings.DATABASE_URL

# Automatically use SQLite in-memory database during tests
if "pytest" in sys.modules or os.getenv("TESTING") == "True":
    DATABASE_URL = "sqlite:///:memory:"

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
    """Initializes database tables."""
    Base.metadata.create_all(bind=engine)
