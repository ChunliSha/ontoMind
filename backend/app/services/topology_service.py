"""Persist, patch, and export business-logic topology graphs."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.models.topology import BusinessLogicTopology, BusinessLogicTopologyNode
from app.repositories.topology_repository import TopologyRepository
from app.schemas.topology import (
    NodeTypeRead,
    TopologyEdgeWrite,
    TopologyGraph,
    TopologyNode,
    TopologyNodeWrite,
    TopologyPatchRequest,
    TopologyRead,
    TopologyRemountRequest,
    TopologySummary,
)
from app.services._utils import parse_uuid, uid
from app.services.topology_index_service import TopologyIndexService
from app.topology.assemble import assemble_properties
from app.topology.layout import layout_topology
from app.topology.logic_graph import LogicNode
from app.topology.node_types import (
    UNGROUNDED_OBJECT_ID,
    UNGROUNDED_TYPE,
    color_for_class,
    get_default_registry,
)
from app.topology.validate import validate_topology


def _try_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(float(value), 2)))


class TopologyService:
    def __init__(self) -> None:
        self.repo = TopologyRepository()
        self.index_svc = TopologyIndexService()

    def node_types(self) -> list[NodeTypeRead]:
        return [
            NodeTypeRead(
                type_key=s.type_key,
                color=s.color,
                extension_id=s.extension_id,
                role=s.role,
            )
            for s in get_default_registry().all()
        ]

    async def persist_extracted(
        self,
        session: AsyncSession,
        *,
        schema_id: uuid.UUID,
        schema_version: int | None,
        task_id: uuid.UUID,
        file_ids: list[str],
        graph: TopologyGraph,
        warnings: list[dict],
        stats: dict[str, Any],
        type_mapping: dict[str, list[str]],
        name: str = "",
        description: str = "",
        ontology_model_id: str | None = None,
    ) -> BusinessLogicTopology:
        validation = {
            "warnings": warnings,
            "type_mapping": type_mapping,
            "stats": {
                k: v
                for k, v in stats.items()
                if k not in {"key_map", "audit"}
            },
        }
        obj = BusinessLogicTopology(
            schema_id=schema_id,
            schema_version=schema_version,
            ontology_model_id=_try_uuid(ontology_model_id),
            name=name or graph.name or "业务逻辑拓扑",
            description=description or graph.description or "",
            source_file_ids=file_ids,
            graph=graph.to_scl(),
            node_count=len(graph.nodes),
            edge_count=len(graph.edges),
            grounded_ratio=_decimal(stats.get("grounded_ratio")),
            validation=validation,
            layout_locked=False,
            status="ready",
            extraction_task_id=task_id,
        )
        obj = await self.repo.create(session, obj)
        for row in self._audit_rows(graph, stats):
            row.topology_id = obj.id
            session.add(row)
        await session.flush()
        return obj

    async def get(self, session: AsyncSession, id: str) -> TopologyRead:
        obj = await self.repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="业务逻辑拓扑不存在")
        return self._to_read(obj)

    async def get_by_task(self, session: AsyncSession, task_id: str) -> TopologyRead:
        obj = await self.repo.get_by_task(session, parse_uuid(task_id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="该任务尚未生成业务逻辑拓扑")
        return self._to_read(obj)

    async def list_by_schema(
        self,
        session: AsyncSession,
        schema_id: str | None = None,
        *,
        schema_version: int | None = None,
        ontology_model_id: str | None = None,
    ) -> list[TopologySummary]:
        rows = await self.repo.list_by_schema(
            session,
            parse_uuid(schema_id) if schema_id else None,
            schema_version=schema_version,
            ontology_model_id=parse_uuid(ontology_model_id) if ontology_model_id else None,
        )
        return [self._to_summary(r) for r in rows]

    async def delete(self, session: AsyncSession, id: str) -> None:
        obj = await self.repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="业务逻辑拓扑不存在")
        await self.repo.delete(session, obj)
        await session.commit()

    async def export_scl(self, session: AsyncSession, id: str) -> dict[str, Any]:
        obj = await self.repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="业务逻辑拓扑不存在")
        graph = obj.graph if isinstance(obj.graph, dict) else {}
        return graph

    async def patch(
        self, session: AsyncSession, id: str, body: TopologyPatchRequest
    ) -> TopologyRead:
        obj = await self.repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="业务逻辑拓扑不存在")
        graph = TopologyGraph.from_scl(obj.graph if isinstance(obj.graph, dict) else {})

        if body.name is not None:
            obj.name = body.name
            graph.name = body.name
        if body.description is not None:
            obj.description = body.description
            graph.description = body.description
        if body.layout_locked is not None:
            obj.layout_locked = body.layout_locked

        if body.graph is not None:
            incoming = TopologyGraph.from_scl(body.graph)
            if not obj.layout_locked and self._positions_changed(graph, incoming):
                obj.layout_locked = True
            graph = incoming
            graph.name = obj.name
            graph.description = obj.description

        if body.update_node is not None:
            graph = self._apply_node_write(graph, body.update_node, obj)

        if body.add_edge is not None:
            graph = self._add_edge(graph, body.add_edge)

        if body.delete_edge_ids:
            keep = {eid for eid in body.delete_edge_ids}
            graph.edges = [e for e in graph.edges if e.id not in keep]

        if body.remount is not None:
            graph = await self._remount(session, obj, graph, body.remount)

        layout_topology(graph, locked=True)
        now = datetime.now().isoformat(timespec="microseconds")
        graph.last_updated = now
        warnings = validate_topology(graph)
        grounded_n = sum(
            1
            for n in graph.nodes
            if (n.properties or {}).get("selectedObjectId") not in (None, "", UNGROUNDED_OBJECT_ID)
        )
        obj.graph = graph.to_scl()
        obj.node_count = len(graph.nodes)
        obj.edge_count = len(graph.edges)
        obj.grounded_ratio = _decimal(round(100.0 * grounded_n / max(len(graph.nodes), 1), 2))
        validation = dict(obj.validation or {})
        validation["warnings"] = warnings
        obj.validation = validation
        await session.commit()
        refreshed = await self.repo.get_by_id(session, obj.id)
        return self._to_read(refreshed or obj)

    def _apply_node_write(
        self,
        graph: TopologyGraph,
        write: TopologyNodeWrite,
        obj: BusinessLogicTopology,
    ) -> TopologyGraph:
        node = graph.node_index().get(write.id)
        if not node:
            raise AppError(ErrorCode.VALIDATION_ERROR, message=f"节点不存在: {write.id}")
        if write.label is not None:
            node.label = write.label
            node.properties = {**(node.properties or {}), "name": write.label}
        if write.properties is not None:
            node.properties = {**(node.properties or {}), **write.properties}
        moved = False
        if write.x is not None and abs(float(node.x) - float(write.x)) > 1:
            node.x = write.x
            moved = True
        if write.y is not None and abs(float(node.y) - float(write.y)) > 1:
            node.y = write.y
            moved = True
        if moved:
            obj.layout_locked = True
        return graph

    def _add_edge(self, graph: TopologyGraph, edge: TopologyEdgeWrite) -> TopologyGraph:
        ids = graph.node_index()
        if edge.source_id not in ids or edge.target_id not in ids:
            raise AppError(ErrorCode.VALIDATION_ERROR, message="边的端点必须是已有节点")
        if edge.source_id == edge.target_id:
            raise AppError(ErrorCode.VALIDATION_ERROR, message="不允许自环")
        from app.schemas.topology import TopologyEdge, TopologyEndpoint

        graph.edges.append(
            TopologyEdge(
                id=str(uuid.uuid4()),
                source=TopologyEndpoint(cell=edge.source_id),
                target=TopologyEndpoint(cell=edge.target_id),
                label=edge.label or "",
            )
        )
        return graph

    async def _remount(
        self,
        session: AsyncSession,
        obj: BusinessLogicTopology,
        graph: TopologyGraph,
        remount: TopologyRemountRequest,
    ) -> TopologyGraph:
        node = graph.node_index().get(remount.node_id)
        if not node:
            raise AppError(ErrorCode.VALIDATION_ERROR, message=f"节点不存在: {remount.node_id}")
        instance_id = (remount.instance_id or "").strip()
        if instance_id in ("", UNGROUNDED_OBJECT_ID, "自定义"):
            instance_id = ""
        index = await self.index_svc.build_index(
            session, str(obj.schema_id), schema_version=obj.schema_version
        )
        inst = index.instances.get(instance_id) if instance_id else None
        if instance_id and inst is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, message="实例不存在或不属于当前 Schema")
        if inst:
            node.type = inst.class_label
            node.color = color_for_class(inst.class_label)
            node.label = inst.label
        else:
            node.color = color_for_class(node.type or UNGROUNDED_TYPE)
        spec = get_default_registry().get(node.type) if get_default_registry().has(node.type) else None
        logic = self._logic_from_node(node, inst.id if inst else None)
        logic.matched_by = "manual" if inst else "unmatched"
        logic.match_score = 1.0 if inst else 0.0
        if inst:
            logic.label = inst.label
            logic.type = inst.class_label
        props = assemble_properties(logic, inst, spec.properties_template if spec else [])
        node.properties = props
        await self._upsert_audit(obj, node, inst.id if inst else None, "manual" if inst else "unmatched")
        return graph

    def _logic_from_node(self, node: TopologyNode, instance_id: str | None) -> LogicNode:
        p = node.properties or {}
        return LogicNode(
            key=node.id,
            type=node.type,
            label=node.label,
            instance_id=instance_id,
            description=p.get("description"),
            judgement_content=p.get("judgementContent"),
            step1_type=p.get("step1Type"),
            step1_analysis=p.get("step1Analysis"),
            user_guide_content=p.get("userGuideContent"),
            summary_content=p.get("summaryContent"),
            interface_name=p.get("interfaceName"),
            request_method=p.get("requestMethod"),
            request_path=p.get("requestPath"),
            request_params=p.get("requestParams"),
            response_params=p.get("responseParams"),
        )

    async def _upsert_audit(
        self,
        obj: BusinessLogicTopology,
        node: TopologyNode,
        instance_id: str | None,
        matched_by: str,
    ) -> None:
        found = next((n for n in obj.nodes if n.node_key == node.id), None)
        inst_uuid = _try_uuid(instance_id)
        if found:
            found.label = node.label
            found.node_type = node.type
            found.instance_id = inst_uuid
            found.matched_by = matched_by
            found.score = Decimal("1") if matched_by == "manual" else Decimal("0")
            return
        obj.nodes.append(
            BusinessLogicTopologyNode(
                topology_id=obj.id,
                node_key=node.id[:64],
                node_type=node.type[:128],
                label=(node.label or "")[:255],
                instance_id=inst_uuid,
                matched_by=matched_by,
                score=Decimal("1") if matched_by == "manual" else Decimal("0"),
            )
        )

    def _audit_rows(self, graph: TopologyGraph, stats: dict[str, Any]) -> list[BusinessLogicTopologyNode]:
        by_id = {a.get("node_id"): a for a in (stats.get("audit") or []) if a.get("node_id")}
        rows: list[BusinessLogicTopologyNode] = []
        for node in graph.nodes:
            audit = by_id.get(node.id, {})
            inst = _try_uuid(audit.get("instance_id") or (node.properties or {}).get("selectedObjectId"))
            matched = audit.get("matched_by") or (
                "unmatched" if not inst else "exact"
            )
            score = audit.get("score")
            rows.append(
                BusinessLogicTopologyNode(
                    node_key=node.id[:64],
                    node_type=(node.type or "")[:128],
                    label=(node.label or "")[:255],
                    instance_id=inst,
                    matched_by=matched if matched in {
                        "exact", "alias", "normalized", "fuzzy", "unmatched", "manual"
                    } else "unmatched",
                    score=Decimal(str(score)) if score is not None else None,
                    evidence={"logic_key": audit.get("node_key"), "label": node.label},
                )
            )
        return rows

    def _positions_changed(self, old: TopologyGraph, new: TopologyGraph) -> bool:
        prev = old.node_index()
        for node in new.nodes:
            was = prev.get(node.id)
            if not was:
                continue
            if abs(float(was.x) - float(node.x)) > 1 or abs(float(was.y) - float(node.y)) > 1:
                return True
        return False

    def _to_summary(self, obj: BusinessLogicTopology) -> TopologySummary:
        ratio = float(obj.grounded_ratio) if obj.grounded_ratio is not None else None
        return TopologySummary(
            id=str(obj.id),
            schema_id=str(obj.schema_id),
            schema_version=obj.schema_version,
            ontology_model_id=uid(obj.ontology_model_id),
            name=obj.name,
            description=obj.description or "",
            node_count=obj.node_count,
            edge_count=obj.edge_count,
            grounded_ratio=ratio,
            layout_locked=obj.layout_locked,
            status=obj.status,
            extraction_task_id=uid(obj.extraction_task_id),
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )

    def _to_read(self, obj: BusinessLogicTopology) -> TopologyRead:
        validation = obj.validation if isinstance(obj.validation, dict) else {}
        summary = self._to_summary(obj)
        return TopologyRead(
            **summary.model_dump(),
            source_file_ids=[str(x) for x in (obj.source_file_ids or [])],
            graph=obj.graph if isinstance(obj.graph, dict) else {},
            validation=validation or None,
            warnings=list(validation.get("warnings") or []),
            type_mapping={
                k: list(v)
                for k, v in (validation.get("type_mapping") or {}).items()
                if isinstance(v, list)
            },
        )
