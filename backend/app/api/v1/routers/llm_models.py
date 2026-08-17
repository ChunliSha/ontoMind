from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.common import PageResponse
from app.schemas.llm import (
    LlmModelCreate,
    LlmModelRead,
    LlmModelTestResult,
    LlmModelUpdate,
    LlmPreset,
)
from app.services.llm_model_service import LlmModelService

router = APIRouter(prefix="/llm-models", tags=["llm-models"])
svc = LlmModelService()


@router.get("/presets", response_model=list[LlmPreset])
async def list_presets():
    return svc.presets()


@router.get("/active", response_model=list[LlmModelRead])
async def list_active_models(session: AsyncSession = Depends(get_session)):
    """供抽取页下拉：仅返回启用中的模型。"""
    return await svc.list_active(session)


@router.get("", response_model=PageResponse[LlmModelRead])
async def list_models(
    source: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list(session, source=source, status=status, page=page, page_size=page_size)


@router.post("", response_model=LlmModelRead, status_code=status.HTTP_201_CREATED)
async def create_model(body: LlmModelCreate, session: AsyncSession = Depends(get_session)):
    return await svc.create(session, body)


@router.patch("/{id}", response_model=LlmModelRead)
async def update_model(
    id: str, body: LlmModelUpdate, session: AsyncSession = Depends(get_session)
):
    return await svc.update(session, id, body)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(id: str, session: AsyncSession = Depends(get_session)):
    await svc.delete(session, id)


@router.post("/{id}/test", response_model=LlmModelTestResult)
async def test_model(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.test_connection(session, id)


@router.post("/{id}/set-default", response_model=LlmModelRead)
async def set_default(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.set_default(session, id)
