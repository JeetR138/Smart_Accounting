from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from smart_accounting.app.database import init_db
from smart_accounting.app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    init_db()
    yield


app = FastAPI(
    title="Smart Accounting Module",
    description="Backend service for Smart Accounting PDF/Excel parsing, AI classification, and Zoho Books posting.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register endpoints router
app.include_router(api_router)


@app.get("/")
def read_root():
    return {
        "status": "healthy",
        "module": "Smart Accounting Backend",
        "version": "1.0.0"
    }
