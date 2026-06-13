from fastapi import APIRouter
from smart_accounting.app.api.endpoints import companies, workflow, auth

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(companies.router, tags=["companies"])
api_router.include_router(workflow.router, tags=["workflow"])
