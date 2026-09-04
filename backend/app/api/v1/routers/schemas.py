from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.common import PageResponse
from app.schemas.extraction import (
    ClearInstancesRequest,
    ClearInstancesResult,
    InstanceInventoryResponse,
    InstanceRead,
    InstanceStatsResponse,
    TaskAccepted,
)
from app.schemas.schema import (
    ClassCreate,
    ClassRead,
    ClassUpdate,
    PropertyCreate,
    PropertyRead,
    PropertyUpdate,
    SchemaCreate,
    SchemaInduceRequest,
    SchemaPublishRequest,
    SchemaRead,
    SchemaUpdate,
)
from app.services.extraction_service import ExtractionService
from app.services.schema_service import SchemaService

router = APIRouter(tags=["schemas"])
svc = SchemaService()
extraction_svc = ExtractionService()


@router.get("/schemas", response_model=PageResponse[SchemaRead])
async def list_schemas(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list(session, search=search, page=page, page_size=page_size)


@router.post("/schemas", response_model=SchemaRead, status_code=status.HTTP_201_CREATED)
async def create_schema(body: SchemaCreate, session: AsyncSession = Depends(get_session)):
    return await svc.create(session, body)


@router.post("/schemas/import-ttl", response_model=SchemaRead, status_code=status.HTTP_201_CREATED)
async def import_ttl(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    raw = await file.read()
    text = raw.decode("utf-8", errors="replace")
    name = (file.filename or "imported").rsplit(".", 1)[0]
    return await svc.import_ttl(session, text, name=name)


@router.get("/schemas/{id}", response_model=SchemaRead)
async def get_schema(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.get(session, id)


@router.patch("/schemas/{id}", response_model=SchemaRead)
async def update_schema(id: str, body: SchemaUpdate, session: AsyncSession = Depends(get_session)):
    return await svc.update(session, id, body)


@router.post("/schemas/{id}/publish", response_model=SchemaRead)
async def publish_schema(
    id: str, body: SchemaPublishRequest, session: AsyncSession = Depends(get_session)
):
    return await svc.publish(session, id, body)


@router.delete("/schemas/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schema(id: str, session: AsyncSession = Depends(get_session)):
    await svc.delete(session, id)


@router.get("/schemas/{id}/classes", response_model=list[ClassRead])
async def list_classes(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.list_classes(session, id)


@router.post("/schemas/{id}/classes", response_model=ClassRead, status_code=status.HTTP_201_CREATED)
async def create_class(id: str, body: ClassCreate, session: AsyncSession = Depends(get_session)):
    return await svc.create_class(session, id, body)


@router.patch("/classes/{class_id}", response_model=ClassRead)
async def update_class(
    class_id: str, body: ClassUpdate, session: AsyncSession = Depends(get_session)
):
    return await svc.update_class(session, class_id, body)


@router.delete("/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_class(class_id: str, session: AsyncSession = Depends(get_session)):
    await svc.delete_class(session, class_id)


@router.get("/classes/{class_id}/properties", response_model=list[PropertyRead])
async def list_properties(class_id: str, session: AsyncSession = Depends(get_session)):
    return await svc.list_properties(session, class_id)


@router.get("/schemas/{id}/properties", response_model=list[PropertyRead])
async def list_schema_properties(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.list_schema_properties(session, id)


@router.post(
    "/classes/{class_id}/properties",
    response_model=PropertyRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_property(
    class_id: str, body: PropertyCreate, session: AsyncSession = Depends(get_session)
):
    return await svc.create_property(session, class_id, body)


@router.patch("/properties/{property_id}", response_model=PropertyRead)
async def update_property(
    property_id: str, body: PropertyUpdate, session: AsyncSession = Depends(get_session)
):
    return await svc.update_property(session, property_id, body)


@router.delete("/properties/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property(property_id: str, session: AsyncSession = Depends(get_session)):
    await svc.delete_property(session, property_id)


@router.post("/schemas/{id}/induce", response_model=TaskAccepted, status_code=status.HTTP_202_ACCEPTED)
async def induce_schema(
    id: str, body: SchemaInduceRequest, session: AsyncSession = Depends(get_session)
):
    return await extraction_svc.induce_schema(session, id, body)


@router.get("/schemas/{id}/export-ttl")
async def export_ttl(
    id: str,
    include_instances: bool = Query(False),
    schema_version: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    ttl = await svc.export_ttl(
        session,
        id,
        include_instances=include_instances,
        schema_version=schema_version,
    )
    return Response(content=ttl, media_type="text/turtle")


@router.get("/schemas/{id}/instance-stats", response_model=InstanceStatsResponse)
async def instance_stats(
    id: str,
    schema_version: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await extraction_svc.instance_stats(session, id, schema_version=schema_version)


@router.get("/schemas/{id}/instance-inventory", response_model=InstanceInventoryResponse)
async def instance_inventory(
    id: str,
    schema_version: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await extraction_svc.instance_inventory(session, id, schema_version=schema_version)


@router.get("/schemas/{id}/instances", response_model=PageResponse[InstanceRead])
async def list_schema_instances(
    id: str,
    schema_version: int | None = Query(None),
    class_id: str | None = Query(None),
    source_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await extraction_svc.list_schema_instances(
        session,
        id,
        schema_version=schema_version,
        class_id=class_id,
        source_type=source_type,
        page=page,
        page_size=page_size,
    )


@router.post("/schemas/{id}/instances/clear", response_model=ClearInstancesResult)
async def clear_schema_instances(
    id: str,
    body: ClearInstancesRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    return await extraction_svc.clear_schema_instances(session, id, body)
