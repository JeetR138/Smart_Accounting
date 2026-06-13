# Smart Accounting - Backend Module

This repository contains the complete backend for the **Smart Accounting** module. It is built using **Python**, **FastAPI**, **MySQL (SQLAlchemy ORM)**, and **Claude AI (Anthropic client)**.

The system is designed with a highly modular, multi-tenant architecture, allowing clean integration into an existing CRM.

---

## Technical Stack
* **Framework**: FastAPI
* **Database**: MySQL (SQLAlchemy ORM)
* **Parser Engine**: `pdfplumber` (for PDF bank statements), `pandas` & `openpyxl` (for Excel spreadsheets)
* **AI Engine**: Claude API (`claude-3-5-sonnet-20241022` / `claude-sonnet-4-20250514`)
* **Testing**: `pytest` & `fastapi.testclient`

---

## Directory Layout
```
smart_accounting/
├── app/
│   ├── api/
│   │   ├── deps.py               # Dependency injection & tenant session verifiers
│   │   ├── router.py             # Combined API routes
│   │   └── endpoints/
│   │       ├── companies.py      # Company and OAuth setup routes
│   │       └── workflow.py       # Document upload and transaction approval routes
│   ├── schemas/
│   │   ├── company.py            # Pydantic schemas for companies
│   │   └── posting.py            # Pydantic schemas for upload & approvals
│   ├── services/
│   │   ├── classification.py     # Claude AI classification logic
│   │   ├── oauth.py              # Zoho Books OAuth token lifecycle
│   │   ├── parser.py             # PDF/Excel layout parsers for WIO, Mashreq, NOMOD, NI, etc.
│   │   ├── posting.py            # Zoho Books API posting and approval orchestrator
│   │   └── security.py           # File upload security (magic bytes & size validation)
│   ├── config.py                 # Application settings loading
│   ├── database.py               # Database engine, session maker, & lifespan initialization
│   ├── main.py                   # FastAPI entrypoint
│   └── models.py                 # MySQL SQLAlchemy model definitions
├── tests/
│   ├── test_api.py               # Router, session authorization, and upload workflow integration tests
│   ├── test_classification.py    # Claude AI classification & mockup tests
│   ├── test_oauth.py             # Zoho OAuth callback & token auto-refresh tests
│   ├── test_parser.py            # PDF/Excel layout normalizers & parsers tests
│   └── test_posting.py           # Zoho Books API poster & retry tenacity tests
├── Dockerfile                    # Container definition
├── docker-compose.yml            # Application & MySQL services compose setup
├── requirements.txt              # Package dependencies
└── README.md                     # Documentation
```

---

## Setup & Running Local Development

### 1. Requirements Setup
Ensure you have Python 3.11+ installed. Create a virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment Variables Config
Copy the `.env.example` file to `.env` and configure your credentials:
```bash
cp .env.example .env
```
Inside `.env`:
* Configure `DATABASE_URL` to point to your MySQL server.
* Configure `ANTHROPIC_API_KEY` for Claude classifications.
* Configure Zoho credentials (`ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, etc.).

### 3. Running the Server Locally
To start the FastAPI dev server:
```bash
PYTHONPATH=. uvicorn smart_accounting.app.main:app --reload --port 8000
```
API Documentation will be accessible at: [http://localhost:8000/docs](http://localhost:8000/docs).

### 4. Running the Complete Test Suite
The test suite operates entirely in memory using a mock SQLite database and mock Claude/Zoho fallbacks when keys are not set:
```bash
PYTHONPATH=. pytest
```

---

## Containerization (Docker)
You can spin up the application along with a MySQL database using Docker Compose:
```bash
docker-compose up --build
```
This starts:
1. `db`: MySQL database container mapping port `3306` with healthcheck hooks.
2. `app`: FastAPI backend application mapping port `8000`.

---

## Key Features

### 1. Multi-Tenant Session Validation & Security
All endpoints require a session token header `X-Session-Token`.
* **General Session Auth**: Block direct endpoint calls without a token (return `401 Unauthorized`).
* **Tenant Isolation**: When calling `/upload`, `/connect-zoho`, or `/approve/{entry_id}`, the session token format `session_{company_id}` is verified. The user cannot access another company's records or tokens by altering the requested `company_id` (returns `403 Forbidden`).

### 2. Upload Penetration Protection
File uploads are validated at the service layer:
* **Extension limits**: Only `.pdf`, `.xlsx`, `.xls` are allowed.
* **Oversized files**: Files larger than 10MB are rejected with `413 Payload Too Large`.
* **Magic byte validation**: File headers are inspected to verify if they are genuine documents. Scripts or malware disguised with a `.pdf` extension are rejected with `400 Bad Request`.

### 3. Mock Testing Mode
If `ANTHROPIC_API_KEY` or `ZOHO_CLIENT_ID` is unset or set to mock defaults:
* The classification service runs in **Mock Classification mode**, returning deterministic mappings.
* The Zoho Books poster runs in **Mock Posting mode**, logging successful transactions to the DB with mock Zoho record IDs.
* This allows full development, manual interface verification, and automated testing to proceed offline without burning API limits or token credentials.

---

## Integration Guide: Inserting into an Existing CRM

This module is designed as an isolated backend system, making it easy to embed into an existing CRM. There are two primary integration patterns:

### Option A: Standalone Microservice (Recommended)
Run this application as a separate microservice and connect to it from your CRM via HTTP/REST.

1. **Deploy the Microservice**: Deploy the Docker container or run the FastAPI app on your servers.
2. **CRM Backend calls**: Configure your CRM backend to make HTTP calls to this service.
   * **Authentication**: Authenticate calls by setting the header:
     `X-Session-Token: session_<company_id>`
   * **Company Sync**: When a tenant registers in your CRM, create a corresponding company row in this service by calling `POST /api/v1/companies/`.
3. **Embed CRM Frontend**:
   * Add a file upload widget in your CRM's UI that uploads statement files to `POST /api/v1/upload?sync=false&auto_clean=false`.
   * Embed a "Flagged Transactions" review page in the CRM dashboard that fetches unapproved items from `GET /api/v1/companies/<company_id>/flagged` and calls `POST /api/v1/companies/<company_id>/approve/<entry_id>` on user approval.
   * Integrate the OAuth setup by linking the user to `GET /api/v1/companies/connect-zoho` to authorize their Zoho Books account.

---

### Option B: Code-Level Merge (Monolith)
If your existing CRM is written in Python (FastAPI, Starlette, or Django), you can merge the codebases.

1. **Copy Source Code**: Copy the `smart_accounting/` package directory directly into your CRM project root.
2. **Register the Router**:
   In your CRM's main FastAPI initialization (e.g., `main.py`), import and mount the smart accounting router:
   ```python
   from smart_accounting.app.api.router import api_router as smart_accounting_router
   app.include_router(smart_accounting_router, prefix="/api/v1")
   ```
3. **Merge Database Models**:
   * Add the SQLAlchemy models in `smart_accounting/app/models.py` to your CRM's database models registry.
   * Generate a database migration using your CRM's migration tool (e.g., `alembic revision --autogenerate` or `python manage.py makemigrations`) to create the required tables:
     * `companies`: Stores company settings and Zoho organization ID.
     * `zoho_tokens`: Stores encrypted Zoho Books OAuth tokens.
     * `jobs`: Tracks parsing progress.
     * `processing_log`: Logs transaction rows and Zoho post outcomes.
4. **Merge Settings**: Add the environment variables from `.env.example` into your CRM's configuration manager (e.g., Pydantic Settings, Django settings).
5. **Adjust Session Dependency**:
   Update `smart_accounting/app/api/deps.py` to use your existing CRM session/auth token resolver so that standard CRM users automatically pass the verification check.
