import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database Configuration
    DATABASE_URL: str = "mysql+pymysql://root:password@localhost:3306/smart_accounting"

    # Anthropic (Claude AI) Configuration
    ANTHROPIC_API_KEY: str = "mock-key-for-testing"
    CLAUDE_MODEL: str = "claude-sonnet-4-6"

    # Zoho Books API Credentials
    ZOHO_CLIENT_ID: str = ""
    ZOHO_CLIENT_SECRET: str = ""
    ZOHO_REDIRECT_URI: str = "http://localhost:8000/api/v1/companies/connect-zoho/callback"

    # Zoho Regional Endpoints
    ZOHO_ACCOUNTS_URL: str = "https://accounts.zoho.com"
    ZOHO_BOOKS_URL: str = "https://www.zohoapis.com/books"

    # Security configuration
    SESSION_SECRET_KEY: str = "dev-secret-key-change-in-production"

    # JWT Authentication settings
    JWT_SECRET_KEY: str = "dev-jwt-secret-key-change-in-production-123456789"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Credentials encryption settings (Fernet AES key)
    # Dev fallback. In production, provide a proper 32-byte base64 Fernet key.
    ENCRYPTION_SECRET_KEY: str = "dev-encryption-key-must-be-32-bytes-base64="

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
