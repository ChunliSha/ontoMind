from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.mapping import (
    MappingCreate,
    MappingRead,
    SourceFieldRead,
    TargetPropertyRead,
)
from app.services.mapping_service import MappingService

router = APIRouter(prefix="/mappings", tags=["mappings"])
svc = MappingService()


@router.get("/source-fields", response_model=list[SourceFieldRead])
async def source_fields(table_id: str = Query(...), session: AsyncSession = Depends(get_session)):
    return await svc.source_fields(session, table_id)


@router.get("/target-properties", response_model=list[TargetPropertyRead])
async def target_properties(
    class_id: str = Query(...), session: AsyncSession = Depends(get_session)
):
    return await svc.target_properties(session, class_id)


@router.get("", response_model=list[MappingRead])
async def list_mappings(
    schema_id: str | None = None,
    class_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    return await svc.list(session, schema_id=schema_id, class_id=class_id)


@router.post("", response_model=MappingRead, status_code=status.HTTP_201_CREATED)
async def save_mapping(body: MappingCreate, session: AsyncSession = Depends(get_session)):
    return await svc.save(session, body)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(id: str, session: AsyncSession = Depends(get_session)):
    await svc.delete(session, id)
