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
from app.knowledge.evidence import Evidence, EvidenceTriple, number_evidences
from app.knowledge.expand import bfs_expand
from app.knowledge.limits import clamp_hops, clamp_limit, clamp_nodes, run_bounded
from app.knowledge.search_rank import score_hit
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
        classes = [
            KnowledgeClassRead(
                id=str(c.id),
                label=c.label,
                local_name=c.local_name,
                description=c.description,
                parent_class_id=uid(c.parent_class_id),
            )
            for c in sl.classes.values()
        ]
        props = []
        for p in sl.properties.values():
            domain = sl.classes.get(p.domain_class_id)
            rng = sl.classes.get(p.range_class_id) if p.range_class_id else None
            props.append(
                KnowledgePropertyRead(
                    id=str(p.id),
                    label=p.label,
                    local_name=p.local_name,
                    kind=p.kind,
                    datatype=p.datatype,
                    domain_class_id=str(p.domain_class_id),
                    domain_class_label=domain.label if domain else None,
                    range_class_id=uid(p.range_class_id),
                    range_class_label=rng.label if rng else None,
                    required=bool(p.required),
                    multi=bool(p.multi),
                )
            )
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
        return KnowledgeClassRead(
            id=str(obj.id),
            label=obj.label,
            local_name=obj.local_name,
            description=obj.description,
            parent_class_id=uid(obj.parent_class_id),
        )

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
        for p in sl.properties.values():
            if domain_id and p.domain_class_id != domain_id:
                continue
            if kind and p.kind != kind:
                continue
            domain = sl.classes.get(p.domain_class_id)
            rng = sl.classes.get(p.range_class_id) if p.range_class_id else None
            items.append(
                KnowledgePropertyRead(
                    id=str(p.id),
                    label=p.label,
                    local_name=p.local_name,
                    kind=p.kind,
                    datatype=p.datatype,
                    domain_class_id=str(p.domain_class_id),
                    domain_class_label=domain.label if domain else None,
                    range_class_id=uid(p.range_class_id),
                    range_class_label=rng.label if rng else None,
                    required=bool(p.required),
                    multi=bool(p.multi),
                )
            )
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
        async def _run() -> KnowledgeSearchResponse:
            started = time.perf_counter()
            sl = await self.resolve_slice(session, ontology_model_id)
            cap = clamp_limit(limit)
            needle = q
            cid: uuid.UUID | None = None
            if class_id:
                cid = parse_uuid(class_id, field="class_id")
            elif class_label:
                cls = sl.class_by_label(class_label)
                if not cls:
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
                    return result
                cid = cls.id
            elif (needle or "").strip():
                linked = sl.class_by_label(needle)
                if linked and _query_is_class_scope(needle, linked.label):
                    cid = linked.id
                    needle = ""
            rows = await self.instance_repo.search(
                session,
                sl.schema_id,
                schema_version=sl.schema_version,
                q=needle or None,
                class_id=cid,
                limit=min(cap * 3, 300),
            )
            scored: list[tuple[float, OntologyInstance]] = []
            for inst in rows:
                cls = sl.classes.get(inst.class_id)
                dv = {}
                for d in inst.data_values or []:
                    prop = sl.properties.get(d.property_id)
                    if prop:
                        dv[prop.label] = d.value
                score = score_hit(
                    needle,
                    label=inst.label,
                    local_name=inst.local_name,
                    class_label=cls.label if cls else None,
                    data_values=dv,
                )
                if not (needle or "").strip():
                    score = 0.5
                scored.append((score, inst))
            scored.sort(key=lambda x: (-x[0], x[1].label))
            hits: list[KnowledgeInstanceHit] = []
            evidences: list[Evidence] = []
            for score, inst in scored[:cap]:
                cls = sl.classes.get(inst.class_id)
                hits.append(
                    KnowledgeInstanceHit(
                        id=str(inst.id),
                        label=inst.label,
                        class_id=str(inst.class_id),
                        class_label=cls.label if cls else None,
                        local_name=inst.local_name,
                        score=round(score, 4),
                        schema_id=str(inst.schema_id),
                    )
                )
                evidences.append(
                    Evidence(
                        id="",
                        kind="instance",
                        entity_id=str(inst.id),
                        label=inst.label,
                        class_label=cls.label if cls else None,
                        properties={"score": round(score, 4)},
                        source_ref=inst.source_ref,
                    )
                )
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

        return await run_bounded(_run())

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
        async def _run() -> KnowledgeInstanceDetail:
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

        return await run_bounded(_run())

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
        async def _run() -> list[KnowledgeRelation]:
            started = time.perf_counter()
            sl = await self.resolve_slice(session, ontology_model_id)
            iid = parse_uuid(instance_id, field="id")
            inst = await self.instance_repo.get_by_id(session, iid)
            if not inst or not self._in_slice(sl, inst):
                raise AppError(ErrorCode.NOT_FOUND, message="实例不存在或不属于该本体模型")
            pid: uuid.UUID | None = None
            pids: list[uuid.UUID] | None = None
            if property_id:
                pid = parse_uuid(property_id, field="property_id")
                pids = [pid]
            elif property_label:
                matched = sl.props_by_label(property_label)
                pids = [p.id for p in matched] or [uuid.UUID(int=0)]
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

        return await run_bounded(_run())

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
        async def _run() -> KnowledgeExpandResponse:
            started = time.perf_counter()
            sl = await self.resolve_slice(session, ontology_model_id)
            hops = clamp_hops(max_hops)
            node_cap = clamp_nodes(max_nodes)
            if len(start_ids) > node_cap:
                raise AppError(ErrorCode.KNOWLEDGE_002, message="起点数量超过 max_nodes", field="start_ids")

            pids: list[uuid.UUID] | None = None
            if predicates:
                found: list[uuid.UUID] = []
                for name in predicates:
                    name = (name or "").strip()
                    if not name:
                        continue
                    try:
                        found.append(parse_uuid(name))
                    except AppError:
                        found.extend(p.id for p in sl.props_by_label(name))
                pids = found or [uuid.UUID(int=0)]

            uuids: list[uuid.UUID] = []
            for sid in start_ids:
                uuids.append(parse_uuid(sid, field="start_ids"))

            # hop-by-hop fetch; never dump the full graph
            collected: list[tuple[str, str, str, str]] = []
            labels: dict[str, str] = {}
            class_labels: dict[str, str | None] = {}
            seen_rel: set[uuid.UUID] = set()
            frontier = list(uuids)
            visited: set[uuid.UUID] = set(uuids)
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
                frontier = nxt

            all_ids = list(visited)
            if all_ids:
                result = await session.execute(
                    select(OntologyInstance).where(OntologyInstance.id.in_(all_ids))
                )
                for inst in result.scalars().all():
                    if not self._in_slice(sl, inst):
                        continue
                    labels[str(inst.id)] = inst.label
                    cls = sl.classes.get(inst.class_id)
                    class_labels[str(inst.id)] = cls.label if cls else None

            start_str = [str(x) for x in uuids]
            node_ids, links = bfs_expand(
                start_str,
                labels,
                collected,
                max_hops=hops,
                max_nodes=node_cap,
            )
            hop_of = {sid: 0 for sid in start_str}
            for link in links:
                hop_of.setdefault(link.object_id, link.hop)
                hop_of.setdefault(link.subject_id, link.hop)

            nodes = [
                KnowledgeExpandNode(
                    id=nid,
                    label=labels.get(nid, nid),
                    class_label=class_labels.get(nid),
                    hop=hop_of.get(nid, 0),
                )
                for nid in node_ids
            ]
            out_links = [
                KnowledgeExpandLink(
                    subject_id=e.subject_id,
                    subject_label=e.subject_label,
                    property_id=e.property_id,
                    property_label=e.property_label,
                    object_id=e.object_id,
                    object_label=e.object_label,
                    hop=e.hop,
                )
                for e in links
            ]
            evids: list[Evidence] = []
            for n in nodes:
                evids.append(
                    Evidence(
                        id="",
                        kind="instance",
                        entity_id=n.id,
                        label=n.label,
                        class_label=n.class_label,
                        properties={"hop": n.hop},
                    )
                )
            for e in links[:50]:
                evids.append(
                    Evidence(
                        id="",
                        kind="triple",
                        entity_id=e.subject_id,
                        label=f"{e.subject_label} -{e.property_label}-> {e.object_label}",
                        triples=[
                            EvidenceTriple(
                                subject_id=e.subject_id,
                                subject_label=e.subject_label,
                                predicate=e.property_label,
                                object_id=e.object_id,
                                object_label=e.object_label,
                            )
                        ],
                    )
                )
            truncated = len(visited) >= node_cap
            resp = KnowledgeExpandResponse(
                nodes=nodes,
                links=out_links,
                evidences=number_evidences(evids),
                truncated=truncated,
            )
            await log_access(
                session,
                caller=caller,
                tool_name="expand_hops",
                ontology_model_id=sl.model.id,
                session_id=session_id,
                trace_id=trace_id,
                latency_ms=int((time.perf_counter() - started) * 1000),
                empty_hit=len(out_links) == 0,
                request_meta={
                    "start_ids": start_str,
                    "max_hops": hops,
                    "node_count": len(nodes),
                    "truncated": truncated,
                },
            )
            return resp

        return await run_bounded(_run())

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
        data: Any
        evidences: list = []
        if plan.action == "search_instances":
            resp = await self.search_instances(
                session,
                ontology_model_id,
                q=str(plan.args.get("q") or ""),
                limit=plan.limit,
                caller=caller,
                trace_id=trace_id,
            )
            data = resp.model_dump()
            evidences = resp.evidences
        elif plan.action == "get_instance":
            detail = await self.get_instance(
                session,
                ontology_model_id,
                str(plan.args["instance_id"]),
                caller=caller,
                trace_id=trace_id,
            )
            data = detail.model_dump()
            evidences = detail.evidences
        elif plan.action == "list_relations":
            rels = await self.list_relations(
                session,
                ontology_model_id,
                str(plan.args["instance_id"]),
                property_label=plan.args.get("property_label"),
                caller=caller,
                trace_id=trace_id,
            )
            data = [r.model_dump() for r in rels]
        else:
            raise AppError(ErrorCode.KNOWLEDGE_002, message="SPARQL 计划无法执行")
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
        return {"ok": True, "plan": {"action": plan.action, "args": plan.args, "limit": plan.limit}, "data": data, "evidences": [e.model_dump() if hasattr(e, "model_dump") else e for e in evidences]}

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

    async def _instance_detail(
        self, session: AsyncSession, sl: ModelSlice, inst: OntologyInstance
    ) -> KnowledgeInstanceDetail:
        cls = sl.classes.get(inst.class_id)
        data_values: list[KnowledgeDataValue] = []
        props_map: dict[str, Any] = {}
        triples: list[EvidenceTriple] = []
        for dv in inst.data_values or []:
            prop = sl.properties.get(dv.property_id)
            label = prop.label if prop else None
            data_values.append(
                KnowledgeDataValue(property_id=str(dv.property_id), property_label=label, value=dv.value)
            )
            if label:
                props_map[label] = dv.value
                triples.append(
                    EvidenceTriple(
                        subject_id=str(inst.id),
                        subject_label=inst.label,
                        predicate=label,
                        object_value=dv.value,
                    )
                )
        rels = await self.relation_repo.list_incident(
            session, [inst.id], schema_id=sl.schema_id, schema_version=sl.schema_version
        )
        relations = await self._map_relations(session, sl, inst.id, rels)
        for rel in relations:
            triples.append(
                EvidenceTriple(
                    subject_id=str(inst.id) if rel.direction == "out" else rel.other_instance_id,
                    subject_label=inst.label if rel.direction == "out" else (rel.other_instance_label or ""),
                    predicate=rel.property_label or "",
                    object_id=rel.other_instance_id if rel.direction == "out" else str(inst.id),
                    object_label=(rel.other_instance_label if rel.direction == "out" else inst.label),
                )
            )
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
            outgoing = rel.subject_instance_id == instance_id
            other_id = rel.object_instance_id if outgoing else rel.subject_instance_id
            other = others.get(other_id)
            if other and not self._in_slice(sl, other):
                continue
            prop = sl.properties.get(rel.property_id)
            ocls = sl.classes.get(other.class_id) if other else None
            items.append(
                KnowledgeRelation(
                    id=str(rel.id),
                    direction="out" if outgoing else "in",
                    property_id=str(rel.property_id),
                    property_label=prop.label if prop else None,
                    other_instance_id=str(other_id),
                    other_instance_label=other.label if other else None,
                    other_class_label=ocls.label if ocls else None,
                )
            )
        return items
