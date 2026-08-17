from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.graph import GraphNodeDetail, GraphResponse
from app.services.graph_service import GraphService

router = APIRouter(prefix="/graph", tags=["graph"])
svc = GraphService()


@router.get("", response_model=GraphResponse)
async def get_graph(
    schema_id: str = Query(...),
    mode: str = Query("mixed"),
    limit: int = Query(500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    return await svc.get_graph(session, schema_id=schema_id, mode=mode, limit=limit)


@router.get("/nodes/{node_id}", response_model=GraphNodeDetail)
async def node_detail(
    node_id: str,
    node_type: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    return await svc.node_detail(session, node_id, node_type=node_type)
