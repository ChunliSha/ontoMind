import json
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.topology import (
    InstanceCatalogResponse,
    NodeTypeRead,
    TopologyPatchRequest,
    TopologyRead,
    TopologySummary,
    TypeMappingSuggestResponse,
)
from app.services.topology_mapping_service import TopologyMappingService
from app.services.topology_service import TopologyService

router = APIRouter(prefix="/business-logic", tags=["business-logic-topology"])
mapping_svc = TopologyMappingService()
topo_svc = TopologyService()


@router.get("/node-types", response_model=list[NodeTypeRead])
async def list_node_types():
    return topo_svc.node_types()


@router.get("/type-mapping/suggest", response_model=TypeMappingSuggestResponse)
async def suggest_type_mapping(
    schema_id: str = Query(...),
    schema_version: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await mapping_svc.suggest(session, schema_id, schema_version=schema_version)


@router.get("/instance-catalog", response_model=InstanceCatalogResponse)
async def instance_catalog(
    schema_id: str = Query(...),
    schema_version: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await mapping_svc.catalog(session, schema_id, schema_version=schema_version)


@router.get("/topologies", response_model=list[TopologySummary])
async def list_topologies(
    schema_id: str | None = Query(None),
    schema_version: int | None = Query(None),
    ontology_model_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await topo_svc.list_by_schema(
        session,
        schema_id,
        schema_version=schema_version,
        ontology_model_id=ontology_model_id,
    )


@router.get("/topologies/{id}", response_model=TopologyRead)
async def get_topology(id: str, session: AsyncSession = Depends(get_session)):
    return await topo_svc.get(session, id)


@router.patch("/topologies/{id}", response_model=TopologyRead)
async def patch_topology(
    id: str,
    body: TopologyPatchRequest,
    session: AsyncSession = Depends(get_session),
):
    return await topo_svc.patch(session, id, body)


@router.delete("/topologies/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topology(id: str, session: AsyncSession = Depends(get_session)):
    await topo_svc.delete(session, id)
    return None


@router.get("/topologies/{id}/export")
async def export_topology(id: str, session: AsyncSession = Depends(get_session)):
    data = await topo_svc.export_scl(session, id)
    raw = (data.get("name") or "business-logic-topology").replace("/", "_").replace("\\", "_")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._") or "business-logic-topology"
    content = json.dumps(data, ensure_ascii=False, indent=2)
    disposition = (
        f'attachment; filename="{ascii_name}.json"; '
        f"filename*=UTF-8''{quote(raw + '.json')}"
    )
    return Response(
        content=content.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )
