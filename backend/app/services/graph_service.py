"""GraphService — assemble {nodes, links} per §9.4."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.repositories.class_repository import ClassRepository
from app.repositories.instance_relation_repository import InstanceRelationRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.property_repository import PropertyRepository
from app.repositories.schema_repository import SchemaRepository
from app.schemas.graph import GraphLink, GraphNode, GraphNodeDetail, GraphResponse
from app.services._utils import parse_uuid

logger = logging.getLogger(__name__)


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
        cached = await self._try_cached_graph(session, sid, mode, limit)
        if cached is not None:
            return cached
        nodes: list[GraphNode] = []
        links: list[GraphLink] = []
        truncated = False
        if mode in ("schema", "mixed"):
            await self._append_schema_graph(session, sid, nodes, links)
        if mode in ("instance", "mixed"):
            truncated = await self._append_instance_graph(
                session, sid, mode, limit, nodes, links
            )
        if len(nodes) > limit:
            truncated = True
            nodes = nodes[:limit]
        await self._store_graph_cache(session, sid, mode, nodes, links)
        msg = "数据量较大，建议按 Schema 缩小范围" if truncated else None
        return GraphResponse(nodes=nodes, links=links, truncated=truncated, message=msg)

    async def _try_cached_graph(
        self, session: AsyncSession, sid, mode: str, limit: int
    ) -> GraphResponse | None:
        cached = await self.schema_repo.get_graph_cache(session, sid, mode)
        if not cached or not isinstance(cached.payload, dict):
            return None
        nodes = cached.payload.get("nodes") or []
        links = cached.payload.get("links") or []
        if len(nodes) > limit:
            return None
        return GraphResponse(
            nodes=[GraphNode.model_validate(node) for node in nodes],
            links=[GraphLink.model_validate(link) for link in links],
        )

    async def _append_schema_graph(
        self, session, sid, nodes: list[GraphNode], links: list[GraphLink]
    ) -> None:
        classes = await self.class_repo.list_by_schema(session, sid)
        props = await self.prop_repo.list_by_schema(session, sid)
        inst_counts = {
            cid: cnt for cid, _label, cnt in await self.instance_repo.count_by_class(session, sid)
        }
        dp_counts: dict = {}
        op_counts: dict = {}
        for prop in props:
            if prop.kind == "data":
                dp_counts[prop.domain_class_id] = dp_counts.get(prop.domain_class_id, 0) + 1
            else:
                op_counts[prop.domain_class_id] = op_counts.get(prop.domain_class_id, 0) + 1
        for cls in classes:
            nodes.append(
                GraphNode(
                    id=f"c_{cls.id}",
                    type="class",
                    label=cls.label,
                    dp=dp_counts.get(cls.id, 0),
                    op=op_counts.get(cls.id, 0),
                    inst=inst_counts.get(cls.id, 0),
                )
            )
        self._append_schema_prop_nodes(props, nodes, links)

    @staticmethod
    def _append_schema_prop_nodes(props, nodes: list[GraphNode], links: list[GraphLink]) -> None:
        for prop in props:
            if prop.kind == "object":
                node_id = f"op_{prop.id}"
                nodes.append(GraphNode(id=node_id, type="obj_prop", label=prop.label))
                links.append(
                    GraphLink(source=f"c_{prop.domain_class_id}", target=node_id, type="schema_link")
                )
                if prop.range_class_id:
                    links.append(
                        GraphLink(
                            source=node_id, target=f"c_{prop.range_class_id}", type="schema_link"
                        )
                    )
                continue
            node_id = f"dp_{prop.id}"
            nodes.append(GraphNode(id=node_id, type="data_prop", label=prop.label))
            links.append(
                GraphLink(source=f"c_{prop.domain_class_id}", target=node_id, type="schema_link")
            )

    async def _append_instance_graph(
        self, session, sid, mode: str, limit: int, nodes: list[GraphNode], links: list[GraphLink]
    ) -> bool:
        instances = await self.instance_repo.list_by_schema(session, sid, limit=limit)
        truncated = len(instances) >= limit
        for inst in instances:
            class_ref = f"c_{inst.class_id}" if inst.class_id else None
            nodes.append(
                GraphNode(
                    id=f"i_{inst.id}",
                    type="instance",
                    label=inst.label,
                    classId=class_ref,
                )
            )
            if mode == "mixed" and class_ref:
                links.append(
                    GraphLink(source=f"i_{inst.id}", target=class_ref, type="instance_of")
                )
        relations = await self.relation_repo.list_by_schema(session, sid, limit=limit)
        prop_labels = {prop.id: prop.label for prop in await self.prop_repo.list_by_schema(session, sid)}
        for rel in relations:
            links.append(
                GraphLink(
                    source=f"i_{rel.subject_instance_id}",
                    target=f"i_{rel.object_instance_id}",
                    type="instance_rel",
                    label=prop_labels.get(rel.property_id),
                )
            )
        return truncated

    async def _store_graph_cache(self, session, sid, mode, nodes, links) -> None:
        payload = {
            "nodes": [node.model_dump() for node in nodes],
            "links": [link.model_dump() for link in links],
        }
        try:
            await self.schema_repo.upsert_graph_cache(session, sid, mode, payload)
        except Exception:  # noqa: BLE001
            logger.warning("graph cache upsert failed for schema %s mode=%s", sid, mode)

    async def node_detail(
        self, session: AsyncSession, node_id: str, *, node_type: str
    ) -> GraphNodeDetail:
        if node_type == "class":
            return await self._class_node_detail(session, node_id)
        if node_type == "instance":
            return await self._instance_node_detail(session, node_id)
        raise AppError(ErrorCode.VALIDATION_ERROR, message="node_type 必须为 class|instance")

    async def _class_node_detail(self, session, node_id: str) -> GraphNodeDetail:
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
                "properties": [{"id": str(prop.id), "label": prop.label, "kind": prop.kind} for prop in props],
            },
        )

    async def _instance_node_detail(self, session, node_id: str) -> GraphNodeDetail:
        raw = node_id.removeprefix("i_")
        inst = await self.instance_repo.get_by_id(session, parse_uuid(raw))
        if not inst:
            raise AppError(ErrorCode.NOT_FOUND, message="实例节点不存在")
        return GraphNodeDetail(
            id=f"i_{inst.id}",
            type="instance",
            label=inst.label,
            details={
                "class_id": str(inst.class_id) if inst.class_id else None,
                "confidence": float(inst.confidence) if inst.confidence is not None else None,
                "source_type": inst.source_type,
                "data_values": [
                    {"property_id": str(data_val.property_id), "value": data_val.value}
                    for data_val in (inst.data_values or [])
                ],
            },
        )
