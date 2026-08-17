from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.common import PageResponse
from app.schemas.data_source import (
    ConnectionTestResult,
    DbSourceCreate,
    DbSourceRead,
    DbSourceUpdate,
    TableRead,
    TableSelectionPatch,
)
from app.services.db_source_service import DbSourceService

router = APIRouter(prefix="/db-sources", tags=["db-sources"])
svc = DbSourceService()


@router.get("", response_model=PageResponse[DbSourceRead])
async def list_db_sources(
    search: str | None = None,
    db_type: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list(
        session, search=search, db_type=db_type, status=status, page=page, page_size=page_size
    )


@router.post("", response_model=DbSourceRead, status_code=status.HTTP_201_CREATED)
async def create_db_source(body: DbSourceCreate, session: AsyncSession = Depends(get_session)):
    return await svc.create(session, body)


@router.post("/test-connection", response_model=ConnectionTestResult)
async def test_draft_connection(body: DbSourceCreate):
    """表单「测试连接」：连接尚未创建时，用表单参数直接探测。"""
    return await svc.test_draft(body)


@router.post("/{id}/test-connection", response_model=ConnectionTestResult)
async def test_connection(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.test_connection(session, id)


@router.get("/{id}/tables", response_model=list[TableRead])
async def list_tables(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.list_tables(session, id)


@router.patch("/{id}/tables/selection", response_model=list[TableRead])
async def patch_selection(
    id: str, body: TableSelectionPatch, session: AsyncSession = Depends(get_session)
):
    return await svc.patch_selection(session, id, body)


@router.patch("/{id}", response_model=DbSourceRead)
async def update_db_source(
    id: str, body: DbSourceUpdate, session: AsyncSession = Depends(get_session)
):
    return await svc.update(session, id, body)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_db_source(id: str, session: AsyncSession = Depends(get_session)):
    await svc.delete(session, id)
