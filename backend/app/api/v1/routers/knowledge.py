"""Read-only Knowledge Service REST API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.knowledge.service import KnowledgeService
from app.schemas.knowledge import (
    KnowledgeAccessLogRead,
    KnowledgeClassRead,
    KnowledgeExpandRequest,
    KnowledgeExpandResponse,
    KnowledgeInstanceDetail,
    KnowledgePropertyRead,
    KnowledgeRelation,
    KnowledgeSchemaRead,
    KnowledgeSearchResponse,
    SparqlSubsetRequest,
)
from app.schemas.ontology_model import OntologyModelRead
from app.schemas.common import PageResponse

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
svc = KnowledgeService()


@router.get("/models", response_model=PageResponse[OntologyModelRead])
async def list_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list_models(session, page=page, page_size=page_size)


@router.get("/schema", response_model=KnowledgeSchemaRead)
async def get_schema(
    ontology_model_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    return await svc.get_schema(session, ontology_model_id)


@router.get("/classes/{class_id}", response_model=KnowledgeClassRead)
async def get_class(
    class_id: str,
    ontology_model_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    return await svc.get_class(session, ontology_model_id, class_id=class_id)


@router.get("/properties", response_model=list[KnowledgePropertyRead])
async def list_properties(
    ontology_model_id: str = Query(...),
    class_id: str | None = Query(None),
    class_label: str | None = Query(None),
    kind: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list_properties(
        session, ontology_model_id, class_id=class_id, class_label=class_label, kind=kind
    )


@router.get("/instances", response_model=KnowledgeSearchResponse)
async def search_instances(
    ontology_model_id: str = Query(...),
    q: str = Query(""),
    class_id: str | None = Query(None),
    class_label: str | None = Query(None),
    limit: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await svc.search_instances(
        session,
        ontology_model_id,
        q=q,
        class_id=class_id,
        class_label=class_label,
        limit=limit,
    )


@router.get("/instances/{id}", response_model=KnowledgeInstanceDetail)
async def get_instance(
    id: str,
    ontology_model_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    return await svc.get_instance(session, ontology_model_id, id)


@router.get("/instances/{id}/relations", response_model=list[KnowledgeRelation])
async def list_relations(
    id: str,
    ontology_model_id: str = Query(...),
    property_id: str | None = Query(None),
    property_label: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list_relations(
        session,
        ontology_model_id,
        id,
        property_id=property_id,
        property_label=property_label,
    )


@router.post("/expand", response_model=KnowledgeExpandResponse)
async def expand_hops(body: KnowledgeExpandRequest, session: AsyncSession = Depends(get_session)):
    return await svc.expand_hops(
        session,
        body.ontology_model_id,
        body.start_ids,
        max_hops=body.max_hops,
        max_nodes=body.max_nodes,
        predicates=body.predicates,
    )


@router.post("/sparql-subset")
async def sparql_subset(body: SparqlSubsetRequest, session: AsyncSession = Depends(get_session)):
    return await svc.execute_sparql_subset(session, body.ontology_model_id, body.query)


@router.get("/access-logs", response_model=list[KnowledgeAccessLogRead])
async def list_access_logs(
    caller: str | None = Query(None),
    tool_name: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    return await svc.list_access_logs(session, caller=caller, tool_name=tool_name, limit=limit)
