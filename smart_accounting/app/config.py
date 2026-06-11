import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database Configuration
    DATABASE_URL: str = "mysql+pymysql://root:password@localhost:3306/smart_accounting"

    # Anthropic (Claude AI) Configuration
    ANTHROPIC_API_KEY: str = "mock-key-for-testing"

    # Zoho Books API Credentials
    ZOHO_CLIENT_ID: str = ""
    ZOHO_CLIENT_SECRET: str = ""
    ZOHO_REDIRECT_URI: str = "http://localhost:8000/api/v1/companies/connect-zoho/callback"

    # Zoho Regional Endpoints
    ZOHO_ACCOUNTS_URL: str = "https://accounts.zoho.com"
    ZOHO_BOOKS_URL: str = "https://www.zohoapis.com/books"

    # Security configuration
    SESSION_SECRET_KEY: str = "dev-secret-key-change-in-production"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
