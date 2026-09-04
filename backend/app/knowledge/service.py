"""Read-only knowledge access bound to an ontology_model (schema + version slice)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.knowledge.access_log import log_access
from app.knowledge.class_link import is_list_question, link_class_label, score_class_label
from app.knowledge.dto import class_read, hits_from_scored, property_read, score_search_rows
from app.knowledge.evidence import Evidence, EvidenceTriple, number_evidences
from app.knowledge.expand import bfs_expand
from app.knowledge.limits import clamp_hops, clamp_limit, clamp_nodes, run_bounded
from app.knowledge.sparql_subset import parse_sparql_subset
from app.models.instance import OntologyInstance
from app.models.knowledge import KnowledgeAccessLog
from app.models.ontology_model import OntologyModel
from app.models.schema import OntologyClass, OntologyProperty
from app.repositories.class_repository import ClassRepository
from app.repositories.instance_relation_repository import InstanceRelationRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.ontology_model_repository import OntologyModelRepository
from app.repositories.property_repository import PropertyRepository
from app.schemas.knowledge import (
    KnowledgeAccessLogRead,
    KnowledgeClassRead,
    KnowledgeDataValue,
    KnowledgeExpandLink,
    KnowledgeExpandNode,
    KnowledgeExpandResponse,
    KnowledgeInstanceDetail,
    KnowledgeInstanceHit,
    KnowledgePropertyRead,
    KnowledgeRelation,
    KnowledgeSchemaRead,
    KnowledgeSearchResponse,
)
from app.services._utils import parse_uuid, uid
from app.services.ontology_model_service import OntologyModelService
from app.topology.normalize import normalize_alias


@dataclass
class ModelSlice:
    model: OntologyModel
    schema_name: str
    classes: dict[uuid.UUID, OntologyClass] = field(default_factory=dict)
    properties: dict[uuid.UUID, OntologyProperty] = field(default_factory=dict)

    @property
    def schema_id(self) -> uuid.UUID:
        return self.model.schema_id

    @property
    def schema_version(self) -> int:
        return self.model.schema_version

    def class_by_label(self, label: str) -> OntologyClass | None:
        needle = (label or "").strip()
        if not needle:
            return None
        for c in self.classes.values():
            if c.label == needle or (c.local_name and c.local_name == needle):
                return c
        names = [c.label for c in self.classes.values()]
        linked = link_class_label(needle, names)
        if not linked:
            return None
        for c in self.classes.values():
            if c.label == linked:
                return c
        return None

    def props_by_label(self, label: str) -> list[OntologyProperty]:
        needle = (label or "").strip()
        return [
            p
            for p in self.properties.values()
            if p.label == needle or (p.local_name and p.local_name == needle)
        ]


def _query_is_class_scope(q: str, class_label: str) -> bool:
    """True when q names a type (list that class), not a specific instance."""
    if is_list_question(q):
        return True
    phrase = (q or "").strip()
    nq = normalize_alias(phrase)
    nl = normalize_alias(class_label)
    if nq and nq == nl:
        return True
    if any(ch.isdigit() for ch in phrase):
        return False
    return len(phrase) <= 4 and score_class_label(phrase, class_label) >= 0.5


class KnowledgeService:
    def __init__(self) -> None:
        self.model_svc = OntologyModelService()
        self.model_repo = OntologyModelRepository()
        self.class_repo = ClassRepository()
        self.prop_repo = PropertyRepository()
        self.instance_repo = InstanceRepository()
        self.relation_repo = InstanceRelationRepository()

    async def resolve_slice(self, session: AsyncSession, ontology_model_id: str) -> ModelSlice:
        try:
            mid = parse_uuid(ontology_model_id, field="ontology_model_id")
        except AppError as exc:
            raise AppError(ErrorCode.KNOWLEDGE_001, message="本体模型不存在") from exc
        model = await self.model_repo.get_by_id(session, mid)
        if not model:
            raise AppError(ErrorCode.KNOWLEDGE_001)
        schema = await self.model_svc.schema_repo.get_by_id(session, model.schema_id)
        classes = await self.class_repo.list_by_schema(session, model.schema_id)
        props = await self.prop_repo.list_by_schema(session, model.schema_id)
        return ModelSlice(
            model=model,
            schema_name=schema.name if schema else "",
            classes={c.id: c for c in classes},
            properties={p.id: p for p in props},
        )

    def _in_slice(self, sl: ModelSlice, inst: OntologyInstance) -> bool:
        if inst.schema_id != sl.schema_id:
            return False
        if inst.schema_version is not None and inst.schema_version != sl.schema_version:
            return False
        return True

    async def list_models(self, session: AsyncSession, *, page: int = 1, page_size: int = 50):
        return await self.model_svc.list(session, page=page, page_size=page_size)

    async def get_schema(
        self, session: AsyncSession, ontology_model_id: str, *, caller: str = "rest", trace_id: str = ""
    ) -> KnowledgeSchemaRead:
        started = time.perf_counter()
        sl = await self.resolve_slice(session, ontology_model_id)
        classes = [class_read(cls) for cls in sl.classes.values()]
        props = [property_read(sl, prop) for prop in sl.properties.values()]
        result = KnowledgeSchemaRead(
            ontology_model_id=str(sl.model.id),
            ontology_model_name=sl.model.name,
            schema_id=str(sl.schema_id),
            schema_name=sl.schema_name,
            schema_version=sl.schema_version,
            classes=classes,
            properties=props,
        )
        await log_access(
            session,
            caller=caller,
            tool_name="get_schema",
            ontology_model_id=sl.model.id,
            trace_id=trace_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            empty_hit=len(classes) == 0,
            request_meta={"class_count": len(classes), "property_count": len(props)},
        )
        return result

    async def get_class(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        *,
        class_id: str | None = None,
        class_label: str | None = None,
        caller: str = "rest",
        trace_id: str = "",
    ) -> KnowledgeClassRead:
        started = time.perf_counter()
        sl = await self.resolve_slice(session, ontology_model_id)
        obj: OntologyClass | None = None
        if class_id:
            obj = sl.classes.get(parse_uuid(class_id, field="class_id"))
        elif class_label:
            obj = sl.class_by_label(class_label)
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="类不存在")
        await log_access(
            session,
            caller=caller,
            tool_name="get_class",
            ontology_model_id=sl.model.id,
            trace_id=trace_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            request_meta={"class_id": str(obj.id), "label": obj.label},
        )
        return class_read(obj)

    async def list_properties(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        *,
        class_id: str | None = None,
        class_label: str | None = None,
        kind: str | None = None,
        caller: str = "rest",
        trace_id: str = "",
    ) -> list[KnowledgePropertyRead]:
        started = time.perf_counter()
        sl = await self.resolve_slice(session, ontology_model_id)
        domain_id: uuid.UUID | None = None
        if class_id:
            domain_id = parse_uuid(class_id, field="class_id")
        elif class_label:
            cls = sl.class_by_label(class_label)
            domain_id = cls.id if cls else uuid.UUID(int=0)
        items: list[KnowledgePropertyRead] = []
        for prop in sl.properties.values():
            if domain_id and prop.domain_class_id != domain_id:
                continue
            if kind and prop.kind != kind:
                continue
            items.append(property_read(sl, prop))
        await log_access(
            session,
            caller=caller,
            tool_name="list_properties",
            ontology_model_id=sl.model.id,
            trace_id=trace_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            empty_hit=len(items) == 0,
            request_meta={"count": len(items), "kind": kind},
        )
        return items

    async def search_instances(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        *,
        q: str = "",
        class_id: str | None = None,
        class_label: str | None = None,
        limit: int | None = None,
        caller: str = "rest",
        trace_id: str = "",
        session_id: str | None = None,
    ) -> KnowledgeSearchResponse:
        return await run_bounded(
            self._search_instances_body(
                session,
                ontology_model_id,
                q=q,
                class_id=class_id,
                class_label=class_label,
                limit=limit,
                caller=caller,
                trace_id=trace_id,
                session_id=session_id,
            )
        )

    async def _search_instances_body(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        *,
        q: str,
        class_id: str | None,
        class_label: str | None,
        limit: int | None,
        caller: str,
        trace_id: str,
        session_id: str | None,
    ) -> KnowledgeSearchResponse:
        started = time.perf_counter()
        sl = await self.resolve_slice(session, ontology_model_id)
        cap = clamp_limit(limit)
        needle, cid, empty = await self._resolve_search_scope(
            session, sl, q, class_id, class_label, caller, trace_id, session_id, started
        )
        if empty is not None:
            return empty
        rows = await self.instance_repo.search(
            session,
            sl.schema_id,
            schema_version=sl.schema_version,
            q=needle or None,
            class_id=cid,
            limit=min(cap * 3, 300),
        )
        scored = score_search_rows(sl, rows, needle)
        hits, evidences = hits_from_scored(sl, scored, cap)
        result = KnowledgeSearchResponse(
            items=hits,
            evidences=number_evidences(evidences),
            empty_hit=len(hits) == 0,
        )
        await log_access(
            session,
            caller=caller,
            tool_name="search_instances",
            ontology_model_id=sl.model.id,
            session_id=session_id,
            trace_id=trace_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            empty_hit=result.empty_hit,
            request_meta={"q": q, "class_id": str(cid) if cid else None, "count": len(hits)},
        )
        return result

    async def _resolve_search_scope(
        self,
        session,
        sl,
        q: str,
        class_id: str | None,
        class_label: str | None,
        caller: str,
        trace_id: str,
        session_id: str | None,
        started: float,
    ):
        needle = q
        cid: uuid.UUID | None = None
        if class_id:
            return needle, parse_uuid(class_id, field="class_id"), None
        if class_label:
            cls = sl.class_by_label(class_label)
            if cls:
                return needle, cls.id, None
            result = KnowledgeSearchResponse(items=[], evidences=[], empty_hit=True)
            await log_access(
                session,
                caller=caller,
                tool_name="search_instances",
                ontology_model_id=sl.model.id,
                session_id=session_id,
                trace_id=trace_id,
                latency_ms=int((time.perf_counter() - started) * 1000),
                empty_hit=True,
                request_meta={"q": q, "class_label": class_label},
            )
            return needle, None, result
        if (needle or "").strip():
            linked = sl.class_by_label(needle)
            if linked and _query_is_class_scope(needle, linked.label):
                return "", linked.id, None
        return needle, cid, None

    async def get_instance(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        instance_id: str,
        *,
        caller: str = "rest",
        trace_id: str = "",
        session_id: str | None = None,
    ) -> KnowledgeInstanceDetail:
        return await run_bounded(
            self._get_instance_body(
                session,
                ontology_model_id,
                instance_id,
                caller=caller,
                trace_id=trace_id,
                session_id=session_id,
            )
        )

    async def _get_instance_body(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        instance_id: str,
        *,
        caller: str,
        trace_id: str,
        session_id: str | None,
    ) -> KnowledgeInstanceDetail:
        started = time.perf_counter()
        sl = await self.resolve_slice(session, ontology_model_id)
        inst = await self.instance_repo.get_by_id(session, parse_uuid(instance_id, field="id"))
        if not inst or not self._in_slice(sl, inst):
            raise AppError(ErrorCode.NOT_FOUND, message="实例不存在或不属于该本体模型")
        detail = await self._instance_detail(session, sl, inst)
        await log_access(
            session,
            caller=caller,
            tool_name="get_instance",
            ontology_model_id=sl.model.id,
            session_id=session_id,
            trace_id=trace_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            empty_hit=False,
            request_meta={"instance_id": str(inst.id), "label": inst.label},
        )
        return detail

    async def list_relations(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        instance_id: str,
        *,
        property_id: str | None = None,
        property_label: str | None = None,
        caller: str = "rest",
        trace_id: str = "",
        session_id: str | None = None,
    ) -> list[KnowledgeRelation]:
        return await run_bounded(
            self._list_relations_body(
                session,
                ontology_model_id,
                instance_id,
                property_id=property_id,
                property_label=property_label,
                caller=caller,
                trace_id=trace_id,
                session_id=session_id,
            )
        )

    async def _list_relations_body(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        instance_id: str,
        *,
        property_id: str | None,
        property_label: str | None,
        caller: str,
        trace_id: str,
        session_id: str | None,
    ) -> list[KnowledgeRelation]:
        started = time.perf_counter()
        sl = await self.resolve_slice(session, ontology_model_id)
        iid = parse_uuid(instance_id, field="id")
        inst = await self.instance_repo.get_by_id(session, iid)
        if not inst or not self._in_slice(sl, inst):
            raise AppError(ErrorCode.NOT_FOUND, message="实例不存在或不属于该本体模型")
        pids = self._relation_property_ids(sl, property_id, property_label)
        rels = await self.relation_repo.list_incident(
            session, [iid], schema_id=sl.schema_id, schema_version=sl.schema_version, property_ids=pids
        )
        items = await self._map_relations(session, sl, iid, rels)
        await log_access(
            session,
            caller=caller,
            tool_name="list_relations",
            ontology_model_id=sl.model.id,
            session_id=session_id,
            trace_id=trace_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            empty_hit=len(items) == 0,
            request_meta={"instance_id": str(iid), "count": len(items)},
        )
        return items

    @staticmethod
    def _relation_property_ids(sl, property_id: str | None, property_label: str | None):
        if property_id:
            return [parse_uuid(property_id, field="property_id")]
        if property_label:
            matched = sl.props_by_label(property_label)
            return [prop.id for prop in matched] or [uuid.UUID(int=0)]
        return None

    async def expand_hops(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        start_ids: list[str],
        *,
        max_hops: int | None = 1,
        max_nodes: int | None = None,
        predicates: list[str] | None = None,
        caller: str = "rest",
        trace_id: str = "",
        session_id: str | None = None,
    ) -> KnowledgeExpandResponse:
        return await run_bounded(
            self._expand_hops_body(
                session,
                ontology_model_id,
                start_ids,
                max_hops=max_hops,
                max_nodes=max_nodes,
                predicates=predicates,
                caller=caller,
                trace_id=trace_id,
                session_id=session_id,
            )
        )

    async def _expand_hops_body(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        start_ids: list[str],
        *,
        max_hops: int | None,
        max_nodes: int | None,
        predicates: list[str] | None,
        caller: str,
        trace_id: str,
        session_id: str | None,
    ) -> KnowledgeExpandResponse:
        started = time.perf_counter()
        sl = await self.resolve_slice(session, ontology_model_id)
        hops = clamp_hops(max_hops)
        node_cap = clamp_nodes(max_nodes)
        if len(start_ids) > node_cap:
            raise AppError(ErrorCode.KNOWLEDGE_002, message='起点数量超过 max_nodes', field='start_ids')
        pids = self._predicate_ids(sl, predicates)
        start_uuids = [parse_uuid(sid, field='start_ids') for sid in start_ids]
        collected, visited = await self._walk_expand(session, sl, start_uuids, hops, node_cap, pids)
        labels, class_labels = await self._expand_labels(session, sl, visited)
        start_str = [str(item) for item in start_uuids]
        node_ids, links = bfs_expand(
            start_str, labels, collected, max_hops=hops, max_nodes=node_cap
        )
        resp = self._expand_response(
            node_ids, links, labels, class_labels, visited, node_cap, start_str
        )
        await log_access(
            session,
            caller=caller,
            tool_name='expand_hops',
            ontology_model_id=sl.model.id,
            session_id=session_id,
            trace_id=trace_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            empty_hit=len(resp.links) == 0,
            request_meta={
                'start_ids': start_str,
                'max_hops': hops,
                'node_count': len(resp.nodes),
                'truncated': resp.truncated,
            },
        )
        return resp

    def _predicate_ids(self, sl, predicates: list[str] | None):
        if not predicates:
            return None
        found: list[uuid.UUID] = []
        for name in predicates:
            name = (name or '').strip()
            if not name:
                continue
            try:
                found.append(parse_uuid(name))
            except AppError:
                found.extend(prop.id for prop in sl.props_by_label(name))
        return found or [uuid.UUID(int=0)]

    async def _walk_expand(self, session, sl, start_uuids, hops, node_cap, pids):
        collected: list[tuple[str, str, str, str]] = []
        seen_rel: set[uuid.UUID] = set()
        frontier = list(start_uuids)
        visited: set[uuid.UUID] = set(start_uuids)
        for _hop in range(hops):
            if not frontier or len(visited) >= node_cap:
                break
            rels = await self.relation_repo.list_incident(
                session,
                frontier,
                schema_id=sl.schema_id,
                schema_version=sl.schema_version,
                property_ids=pids,
            )
            frontier = self._collect_expand_hop(rels, sl, collected, seen_rel, visited, node_cap)
        return collected, visited

    @staticmethod
    def _collect_expand_hop(rels, sl, collected, seen_rel, visited, node_cap):
        nxt: list[uuid.UUID] = []
        neighbor_ids: set[uuid.UUID] = set()
        for rel in rels:
            if rel.id in seen_rel:
                continue
            seen_rel.add(rel.id)
            prop = sl.properties.get(rel.property_id)
            collected.append(
                (
                    str(rel.subject_instance_id),
                    str(rel.property_id),
                    prop.label if prop else str(rel.property_id),
                    str(rel.object_instance_id),
                )
            )
            for nid in (rel.subject_instance_id, rel.object_instance_id):
                if nid not in visited:
                    neighbor_ids.add(nid)
        for nid in neighbor_ids:
            if len(visited) >= node_cap:
                break
            visited.add(nid)
            nxt.append(nid)
        return nxt

    async def _expand_labels(self, session, sl, visited):
        labels: dict[str, str] = {}
        class_labels: dict[str, str | None] = {}
        all_ids = list(visited)
        if not all_ids:
            return labels, class_labels
        result = await session.execute(
            select(OntologyInstance).where(OntologyInstance.id.in_(all_ids))
        )
        for inst in result.scalars().all():
            if not self._in_slice(sl, inst):
                continue
            labels[str(inst.id)] = inst.label
            cls = sl.classes.get(inst.class_id)
            class_labels[str(inst.id)] = cls.label if cls else None
        return labels, class_labels

    @staticmethod
    def _expand_hop_map(links, start_str) -> dict[str, int]:
        hop_of = {sid: 0 for sid in start_str}
        for link in links:
            hop_of.setdefault(link.object_id, link.hop)
            hop_of.setdefault(link.subject_id, link.hop)
        return hop_of

    @staticmethod
    def _expand_nodes(node_ids, labels, class_labels, hop_of) -> list[KnowledgeExpandNode]:
        return [
            KnowledgeExpandNode(
                id=nid,
                label=labels.get(nid, nid),
                class_label=class_labels.get(nid),
                hop=hop_of.get(nid, 0),
            )
            for nid in node_ids
        ]

    @staticmethod
    def _expand_links(links) -> list[KnowledgeExpandLink]:
        return [
            KnowledgeExpandLink(
                subject_id=edge.subject_id,
                subject_label=edge.subject_label,
                property_id=edge.property_id,
                property_label=edge.property_label,
                object_id=edge.object_id,
                object_label=edge.object_label,
                hop=edge.hop,
            )
            for edge in links
        ]

    @staticmethod
    def _expand_evidences(nodes, links) -> list[Evidence]:
        evids: list[Evidence] = []
        for node in nodes:
            evids.append(
                Evidence(
                    id="",
                    kind="instance",
                    entity_id=node.id,
                    label=node.label,
                    class_label=node.class_label,
                    properties={"hop": node.hop},
                )
            )
        for edge in links[:50]:
            evids.append(
                Evidence(
                    id="",
                    kind="triple",
                    entity_id=edge.subject_id,
                    label=f"{edge.subject_label} -{edge.property_label}-> {edge.object_label}",
                    triples=[
                        EvidenceTriple(
                            subject_id=edge.subject_id,
                            subject_label=edge.subject_label,
                            predicate=edge.property_label,
                            object_id=edge.object_id,
                            object_label=edge.object_label,
                        )
                    ],
                )
            )
        return evids

    @staticmethod
    def _expand_response(node_ids, links, labels, class_labels, visited, node_cap, start_str):
        hop_of = KnowledgeService._expand_hop_map(links, start_str)
        nodes = KnowledgeService._expand_nodes(node_ids, labels, class_labels, hop_of)
        truncated = len(visited) >= node_cap
        return KnowledgeExpandResponse(
            nodes=nodes,
            links=KnowledgeService._expand_links(links),
            evidences=number_evidences(KnowledgeService._expand_evidences(nodes, links)),
            truncated=truncated,
        )


    async def execute_sparql_subset(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        query: str,
        *,
        caller: str = "rest",
        trace_id: str = "",
    ) -> dict[str, Any]:
        """Map a restricted SELECT subset onto KnowledgeService (Postgres remains SoT)."""
        started = time.perf_counter()
        plan = parse_sparql_subset(query)
        data, evidences = await self._run_sparql_plan(
            session, ontology_model_id, plan, caller, trace_id
        )
        await log_access(
            session,
            caller=caller,
            tool_name="sparql_subset",
            ontology_model_id=ontology_model_id,
            trace_id=trace_id,
            plan={"action": plan.action, "args": plan.args},
            latency_ms=int((time.perf_counter() - started) * 1000),
            empty_hit=not data,
            request_meta={"query": query[:500]},
        )
        dumped = [
            item.model_dump() if hasattr(item, "model_dump") else item for item in evidences
        ]
        return {
            "ok": True,
            "plan": {"action": plan.action, "args": plan.args, "limit": plan.limit},
            "data": data,
            "evidences": dumped,
        }

    async def _run_sparql_plan(self, session, ontology_model_id, plan, caller, trace_id):
        if plan.action == "search_instances":
            resp = await self.search_instances(
                session,
                ontology_model_id,
                q=str(plan.args.get("q") or ""),
                limit=plan.limit,
                caller=caller,
                trace_id=trace_id,
            )
            return resp.model_dump(), resp.evidences
        if plan.action == "get_instance":
            detail = await self.get_instance(
                session,
                ontology_model_id,
                str(plan.args["instance_id"]),
                caller=caller,
                trace_id=trace_id,
            )
            return detail.model_dump(), detail.evidences
        if plan.action == "list_relations":
            rels = await self.list_relations(
                session,
                ontology_model_id,
                str(plan.args["instance_id"]),
                property_label=plan.args.get("property_label"),
                caller=caller,
                trace_id=trace_id,
            )
            return [rel.model_dump() for rel in rels], []
        raise AppError(ErrorCode.KNOWLEDGE_002, message="SPARQL 计划无法执行")

    async def list_access_logs(
        self,
        session: AsyncSession,
        *,
        caller: str | None = None,
        tool_name: str | None = None,
        limit: int = 50,
    ) -> list[KnowledgeAccessLogRead]:
        cap = clamp_limit(limit, default=50)
        stmt = select(KnowledgeAccessLog).order_by(KnowledgeAccessLog.created_at.desc()).limit(cap)
        if caller:
            stmt = stmt.where(KnowledgeAccessLog.caller == caller)
        if tool_name:
            stmt = stmt.where(KnowledgeAccessLog.tool_name == tool_name)
        rows = list((await session.execute(stmt)).scalars().all())
        return [
            KnowledgeAccessLogRead(
                id=str(r.id),
                created_at=r.created_at,
                caller=r.caller,
                tool_name=r.tool_name,
                ontology_model_id=uid(r.ontology_model_id),
                session_id=uid(r.session_id),
                trace_id=r.trace_id,
                latency_ms=r.latency_ms,
                empty_hit=r.empty_hit,
                error=r.error,
                request_meta=r.request_meta,
            )
            for r in rows
        ]

    def _collect_instance_props(self, sl: ModelSlice, inst: OntologyInstance):
        data_values: list[KnowledgeDataValue] = []
        props_map: dict[str, Any] = {}
        triples: list[EvidenceTriple] = []
        for data_val in inst.data_values or []:
            prop = sl.properties.get(data_val.property_id)
            label = prop.label if prop else None
            data_values.append(
                KnowledgeDataValue(
                    property_id=str(data_val.property_id),
                    property_label=label,
                    value=data_val.value,
                )
            )
            if not label:
                continue
            props_map[label] = data_val.value
            triples.append(
                EvidenceTriple(
                    subject_id=str(inst.id),
                    subject_label=inst.label,
                    predicate=label,
                    object_value=data_val.value,
                )
            )
        return data_values, props_map, triples

    @staticmethod
    def _relation_triples(inst: OntologyInstance, relations: list[KnowledgeRelation]):
        triples: list[EvidenceTriple] = []
        for rel in relations:
            outgoing = rel.direction == "out"
            triples.append(
                EvidenceTriple(
                    subject_id=str(inst.id) if outgoing else rel.other_instance_id,
                    subject_label=inst.label if outgoing else (rel.other_instance_label or ""),
                    predicate=rel.property_label or "",
                    object_id=rel.other_instance_id if outgoing else str(inst.id),
                    object_label=(rel.other_instance_label if outgoing else inst.label),
                )
            )
        return triples

    async def _instance_detail(
        self, session: AsyncSession, sl: ModelSlice, inst: OntologyInstance
    ) -> KnowledgeInstanceDetail:
        cls = sl.classes.get(inst.class_id)
        data_values, props_map, triples = self._collect_instance_props(sl, inst)
        rels = await self.relation_repo.list_incident(
            session, [inst.id], schema_id=sl.schema_id, schema_version=sl.schema_version
        )
        relations = await self._map_relations(session, sl, inst.id, rels)
        triples.extend(self._relation_triples(inst, relations))
        evid = Evidence(
            id="E1",
            kind="instance",
            entity_id=str(inst.id),
            label=inst.label,
            class_label=cls.label if cls else None,
            properties=props_map,
            triples=triples,
            source_ref=inst.source_ref,
        )
        return KnowledgeInstanceDetail(
            id=str(inst.id),
            label=inst.label,
            class_id=str(inst.class_id),
            class_label=cls.label if cls else None,
            local_name=inst.local_name,
            schema_id=str(inst.schema_id),
            schema_version=inst.schema_version,
            source_type=inst.source_type,
            source_ref=inst.source_ref,
            data_values=data_values,
            relations=relations,
            evidences=[evid],
        )

    async def _map_relations(
        self,
        session: AsyncSession,
        sl: ModelSlice,
        instance_id: uuid.UUID,
        rels: list,
    ) -> list[KnowledgeRelation]:
        other_ids = []
        for rel in rels:
            oid = rel.object_instance_id if rel.subject_instance_id == instance_id else rel.subject_instance_id
            other_ids.append(oid)
        others: dict[uuid.UUID, OntologyInstance] = {}
        if other_ids:
            result = await session.execute(select(OntologyInstance).where(OntologyInstance.id.in_(other_ids)))
            others = {o.id: o for o in result.scalars().all()}
        items: list[KnowledgeRelation] = []
        for rel in rels:
            item = self._relation_item(sl, instance_id, rel, others)
            if item is not None:
                items.append(item)
        return items

    def _relation_item(self, sl, instance_id, rel, others) -> KnowledgeRelation | None:
        outgoing = rel.subject_instance_id == instance_id
        other_id = rel.object_instance_id if outgoing else rel.subject_instance_id
        other = others.get(other_id)
        if other and not self._in_slice(sl, other):
            return None
        prop = sl.properties.get(rel.property_id)
        ocls = sl.classes.get(other.class_id) if other else None
        return KnowledgeRelation(
            id=str(rel.id),
            direction="out" if outgoing else "in",
            property_id=str(rel.property_id),
            property_label=prop.label if prop else None,
            other_instance_id=str(other_id),
            other_instance_label=other.label if other else None,
            other_class_label=ocls.label if ocls else None,
        )
