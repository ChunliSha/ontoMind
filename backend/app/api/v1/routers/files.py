from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.common import PageResponse
from app.schemas.data_source import (
    BuildTableSqlResponse,
    FilePreview,
    FileRead,
    FileUpdate,
    MaterializeTableRequest,
    TableRead,
)
from app.services.file_service import FileService

router = APIRouter(prefix="/files", tags=["files"])
svc = FileService()


@router.get("", response_model=PageResponse[FileRead])
async def list_files(
    search: str | None = None,
    file_type: str | None = None,
    status: str | None = None,
    storage_backend: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list(
        session,
        search=search,
        file_type=file_type,
        status=status,
        storage_backend=storage_backend,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=FileRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    storage_backend: str = Form("local"),
    session: AsyncSession = Depends(get_session),
):
    return await svc.upload(session, file, storage_backend=storage_backend)


@router.get("/{id}", response_model=FileRead)
async def get_file(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.get(session, id)


@router.post("/{id}/reparse", response_model=FileRead)
async def reparse_file(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.reparse(session, id)


@router.get("/{id}/preview", response_model=FilePreview)
async def preview_file(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.preview(session, id)


@router.get("/{id}/download")
async def download_file(id: str, session: AsyncSession = Depends(get_session)):
    name, data = await svc.download(session, id)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.patch("/{id}", response_model=FileRead)
async def update_file(id: str, body: FileUpdate, session: AsyncSession = Depends(get_session)):
    return await svc.update(session, id, body)


@router.post("/{id}/convert-standard-md", response_model=FileRead)
async def convert_standard_md(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.convert_standard_md(session, id)


@router.post("/{id}/convert-ontology-md", response_model=FileRead)
async def convert_ontology_md(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.convert_ontology_md(session, id)


@router.post("/{id}/build-table-sql", response_model=BuildTableSqlResponse)
async def build_table_sql(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.build_table_sql(session, id)


@router.post("/{id}/materialize-table", response_model=TableRead)
async def materialize_table(
    id: str, body: MaterializeTableRequest | None = None, session: AsyncSession = Depends(get_session)
):
    return await svc.materialize_table(session, id, body or MaterializeTableRequest())


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(id: str, session: AsyncSession = Depends(get_session)):
    await svc.delete(session, id)
