from fastapi import APIRouter

from app.api.v1.routers import (
    business_logic,
    dashboard,
    db_sources,
    files,
    graph,
    instances,
    llm_models,
    mappings,
    schemas,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(db_sources.router)
api_router.include_router(files.router)
api_router.include_router(schemas.router)
api_router.include_router(mappings.router)
api_router.include_router(instances.router)
api_router.include_router(business_logic.router)
api_router.include_router(graph.router)
api_router.include_router(dashboard.router)
api_router.include_router(llm_models.router)
