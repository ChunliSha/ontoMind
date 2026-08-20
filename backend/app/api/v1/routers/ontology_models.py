from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.common import PageResponse
from app.schemas.ontology_model import OntologyModelCreate, OntologyModelRead, OntologyModelUpdate
from app.services.ontology_model_service import OntologyModelService

router = APIRouter(prefix="/ontology-models", tags=["ontology-models"])
svc = OntologyModelService()


@router.get("", response_model=PageResponse[OntologyModelRead])
async def list_ontology_models(
    schema_id: str | None = Query(None),
    search: str | None = Query(None),
    min_instances: int = Query(0, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list(
        session,
        schema_id=schema_id,
        search=search,
        min_instances=min_instances,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=OntologyModelRead, status_code=status.HTTP_201_CREATED)
async def create_ontology_model(
    body: OntologyModelCreate, session: AsyncSession = Depends(get_session)
):
    return await svc.create(session, body)


@router.get("/{id}", response_model=OntologyModelRead)
async def get_ontology_model(id: str, session: AsyncSession = Depends(get_session)):
    return await svc.get(session, id)


@router.patch("/{id}", response_model=OntologyModelRead)
async def update_ontology_model(
    id: str, body: OntologyModelUpdate, session: AsyncSession = Depends(get_session)
):
    return await svc.update(session, id, body)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ontology_model(id: str, session: AsyncSession = Depends(get_session)):
    await svc.delete(session, id)
    return None
