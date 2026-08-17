"""GraphService — assemble {nodes, links} per §9.4."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.repositories.class_repository import ClassRepository
from app.repositories.instance_relation_repository import InstanceRelationRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.property_repository import PropertyRepository
from app.repositories.schema_repository import SchemaRepository
from app.schemas.graph import GraphLink, GraphNode, GraphNodeDetail, GraphResponse
from app.services._utils import parse_uuid


class GraphService:
    def __init__(self) -> None:
        self.schema_repo = SchemaRepository()
        self.class_repo = ClassRepository()
        self.prop_repo = PropertyRepository()
        self.instance_repo = InstanceRepository()
        self.relation_repo = InstanceRelationRepository()

    async def get_graph(
        self,
        session: AsyncSession,
        *,
        schema_id: str,
        mode: str = "mixed",
        limit: int = 500,
    ) -> GraphResponse:
        if mode not in ("schema", "instance", "mixed"):
            raise AppError(ErrorCode.VALIDATION_ERROR, message="mode 必须为 schema|instance|mixed")
        sid = parse_uuid(schema_id)
        schema = await self.schema_repo.get_by_id(session, sid)
        if not schema:
            raise AppError(ErrorCode.GRAPH_001)

        # optional cache
        cached = await self.schema_repo.get_graph_cache(session, sid, mode)
        if cached and isinstance(cached.payload, dict):
            nodes = cached.payload.get("nodes") or []
            links = cached.payload.get("links") or []
            if len(nodes) <= limit:
                return GraphResponse(
                    nodes=[GraphNode.model_validate(n) for n in nodes],
                    links=[GraphLink.model_validate(l) for l in links],
                )

        nodes: list[GraphNode] = []
        links: list[GraphLink] = []
        truncated = False

        if mode in ("schema", "mixed"):
            classes = await self.class_repo.list_by_schema(session, sid)
            props = await self.prop_repo.list_by_schema(session, sid)
            inst_counts = {
                cid: cnt for cid, _label, cnt in await self.instance_repo.count_by_class(session, sid)
            }
            dp_counts: dict = {}
            op_counts: dict = {}
            for p in props:
                if p.kind == "data":
                    dp_counts[p.domain_class_id] = dp_counts.get(p.domain_class_id, 0) + 1
                else:
                    op_counts[p.domain_class_id] = op_counts.get(p.domain_class_id, 0) + 1

            for c in classes:
                nodes.append(
                    GraphNode(
                        id=f"c_{c.id}",
                        type="class",
                        label=c.label,
                        dp=dp_counts.get(c.id, 0),
                        op=op_counts.get(c.id, 0),
                        inst=inst_counts.get(c.id, 0),
                    )
                )
            for p in props:
                if p.kind == "object":
                    nid = f"op_{p.id}"
                    nodes.append(GraphNode(id=nid, type="obj_prop", label=p.label))
                    links.append(
                        GraphLink(source=f"c_{p.domain_class_id}", target=nid, type="schema_link")
                    )
                    if p.range_class_id:
                        links.append(
                            GraphLink(
                                source=nid, target=f"c_{p.range_class_id}", type="schema_link"
                            )
                        )
                else:
                    nid = f"dp_{p.id}"
                    nodes.append(GraphNode(id=nid, type="data_prop", label=p.label))
                    links.append(
                        GraphLink(source=f"c_{p.domain_class_id}", target=nid, type="schema_link")
                    )

        if mode in ("instance", "mixed"):
            instances = await self.instance_repo.list_by_schema(session, sid, limit=limit)
            if len(instances) >= limit:
                truncated = True
            for inst in instances:
                nodes.append(
                    GraphNode(
                        id=f"i_{inst.id}",
                        type="instance",
                        label=inst.label,
                        classId=f"c_{inst.class_id}",
                    )
                )
                if mode == "mixed":
                    links.append(
                        GraphLink(
                            source=f"i_{inst.id}",
                            target=f"c_{inst.class_id}",
                            type="instance_of",
                        )
                    )
            relations = await self.relation_repo.list_by_schema(session, sid, limit=limit)
            prop_labels = {
                p.id: p.label for p in await self.prop_repo.list_by_schema(session, sid)
            }
            for rel in relations:
                links.append(
                    GraphLink(
                        source=f"i_{rel.subject_instance_id}",
                        target=f"i_{rel.object_instance_id}",
                        type="instance_rel",
                        label=prop_labels.get(rel.property_id),
                    )
                )

        if len(nodes) > limit:
            truncated = True
            nodes = nodes[:limit]

        payload = {
            "nodes": [n.model_dump() for n in nodes],
            "links": [l.model_dump() for l in links],
        }
        try:
            await self.schema_repo.upsert_graph_cache(session, sid, mode, payload)
        except Exception:  # noqa: BLE001
            pass

        msg = "数据量较大，建议按 Schema 缩小范围" if truncated else None
        return GraphResponse(nodes=nodes, links=links, truncated=truncated, message=msg)

    async def node_detail(
        self, session: AsyncSession, node_id: str, *, node_type: str
    ) -> GraphNodeDetail:
        if node_type == "class":
            raw = node_id.removeprefix("c_")
            cls = await self.class_repo.get_by_id(session, parse_uuid(raw))
            if not cls:
                raise AppError(ErrorCode.NOT_FOUND, message="类节点不存在")
            props = await self.prop_repo.list_by_class(session, cls.id)
            return GraphNodeDetail(
                id=f"c_{cls.id}",
                type="class",
                label=cls.label,
                details={
                    "description": cls.description,
                    "local_name": cls.local_name,
                    "properties": [{"id": str(p.id), "label": p.label, "kind": p.kind} for p in props],
                },
            )
        if node_type == "instance":
            raw = node_id.removeprefix("i_")
            inst = await self.instance_repo.get_by_id(session, parse_uuid(raw))
            if not inst:
                raise AppError(ErrorCode.NOT_FOUND, message="实例节点不存在")
            return GraphNodeDetail(
                id=f"i_{inst.id}",
                type="instance",
                label=inst.label,
                details={
                    "class_id": str(inst.class_id),
                    "confidence": float(inst.confidence) if inst.confidence is not None else None,
                    "source_type": inst.source_type,
                    "data_values": [
                        {"property_id": str(dv.property_id), "value": dv.value}
                        for dv in (inst.data_values or [])
                    ],
                },
            )
        raise AppError(ErrorCode.VALIDATION_ERROR, message="node_type 必须为 class|instance")
