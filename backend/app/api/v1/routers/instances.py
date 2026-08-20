from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.common import PageResponse
from app.schemas.extraction import (
    BusinessLogicExtractionRequest,
    ExtractionTaskRead,
    InstanceRead,
    StructuredExtractionRequest,
    TaskAccepted,
    UnstructuredExtractionRequest,
)
from app.schemas.business_logic import BusinessLogicRuleRead
from app.schemas.topology import TopologyRead
from app.services.business_logic_service import BusinessLogicService
from app.services.extraction_service import ExtractionService
from app.services.topology_service import TopologyService

router = APIRouter(tags=["extraction"])
svc = ExtractionService()
biz_svc = BusinessLogicService()
topo_svc = TopologyService()


@router.post(
    "/extraction/instances/unstructured",
    response_model=TaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def extract_unstructured(
    body: UnstructuredExtractionRequest, session: AsyncSession = Depends(get_session)
):
    return await svc.run_unstructured(session, body)


@router.post(
    "/extraction/instances/structured",
    response_model=TaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def extract_structured(
    body: StructuredExtractionRequest, session: AsyncSession = Depends(get_session)
):
    return await svc.run_structured(session, body)


@router.get("/extraction/tasks", response_model=list[ExtractionTaskRead])
async def list_tasks(
    task_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list_tasks(session, task_type=task_type, status=status, limit=limit)


@router.get("/extraction/tasks/{id}", response_model=ExtractionTaskRead)
async def get_task(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.get_task(session, id)


@router.get("/extraction/tasks/{id}/instances", response_model=PageResponse[InstanceRead])
async def task_instances(
    id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list_task_instances(session, id, page=page, page_size=page_size)


@router.get("/instances/{id}", response_model=InstanceRead)
async def get_instance(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.get_instance(session, id)


@router.post(
    "/extraction/business-logic",
    response_model=TaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def extract_business_logic(
    body: BusinessLogicExtractionRequest, session: AsyncSession = Depends(get_session)
):
    return await svc.run_business_logic(session, body)


@router.get("/extraction/tasks/{id}/rules", response_model=list[BusinessLogicRuleRead])
async def task_rules(id: str, session: AsyncSession = Depends(get_session)):
    return await biz_svc.list_by_task(session, id)


@router.get("/extraction/tasks/{id}/topology", response_model=TopologyRead)
async def task_topology(id: str, session: AsyncSession = Depends(get_session)):
    return await topo_svc.get_by_task(session, id)
