"""QA tool dispatch loop (kept separate so QaAgent methods stay short)."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.openai_compatible_provider import OpenAICompatibleProvider
from app.core.exceptions import AppError, ErrorCode
from app.knowledge.class_link import is_list_question, link_class_label
from app.knowledge.evidence import Evidence, merge_evidences
from app.knowledge.limits import clamp_hops, clamp_limit, clamp_nodes

logger = logging.getLogger("app.qa.agent")


@dataclass
class ToolLoopState:
    last_ids: list[str] = field(default_factory=list)
    evidences: list[Evidence] = field(default_factory=list)
    focus: dict[str, Any] = field(default_factory=dict)


def is_uuid_str(value: Any) -> bool:
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def ground_search_args(args: dict[str, Any], class_labels: list[str], question: str) -> dict[str, Any]:
    out = dict(args)
    labels = class_labels or []
    class_label = str(out.get("class_label") or "").strip()
    query = str(out.get("q") or out.get("query") or "").strip()
    if class_label:
        out = _bind_or_drop_class_label(out, class_label, labels)
        class_label = str(out.get("class_label") or "")
    if not out.get("class_label") and (query or question):
        out = _infer_class_from_query(out, query, question, labels)
    if out.get("class_label") and is_list_question(question):
        out["q"] = ""
    return out


def _bind_or_drop_class_label(out: dict[str, Any], class_label: str, labels: list[str]) -> dict[str, Any]:
    linked = link_class_label(class_label, labels)
    if linked:
        out["class_label"] = linked
        return out
    if class_label not in labels:
        out.pop("class_label", None)
    return out


def _infer_class_from_query(
    out: dict[str, Any], query: str, question: str, labels: list[str]
) -> dict[str, Any]:
    linked = link_class_label(query or question, labels) or link_class_label(question, labels)
    if not linked:
        return out
    listing = is_list_question(question) or is_list_question(query) or not query
    short_type = len(query) <= 4 and not any(char.isdigit() for char in query)
    if listing or short_type:
        out["class_label"] = linked
        out["q"] = ""
    return out


class QaToolMixin:
    async def _run_tools(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        plan: dict[str, Any],
        resolved: dict[str, Any],
        *,
        provider: OpenAICompatibleProvider | None = None,
        class_labels: list[str] | None = None,
        question: str = "",
        caller: str,
        trace_id: str,
        session_id: str,
    ) -> tuple[list[Evidence], list[dict[str, Any]], dict[str, Any]]:
        state = _initial_state(resolved)
        whitelist_preds = self._object_property_labels_from_plan(plan)
        trace: list[dict[str, Any]] = []
        labels = class_labels or []
        for step in plan.get("tools") or []:
            entry = await self._run_one_tool(
                session,
                ontology_model_id,
                step,
                state,
                provider=provider,
                class_labels=labels,
                question=question,
                caller=caller,
                trace_id=trace_id,
                session_id=session_id,
                whitelist_preds=whitelist_preds,
            )
            trace.append(entry)
        return merge_evidences(state.evidences), trace, state.focus

    async def _run_one_tool(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        step: dict[str, Any],
        state: ToolLoopState,
        **ctx,
    ) -> dict[str, Any]:
        name = step["name"]
        args = dict(step.get("args") or {})
        started = time.perf_counter()
        error = None
        summary: Any = None
        try:
            summary = await self._dispatch_tool(
                session, ontology_model_id, name, args, state, **ctx
            )
        except AppError as exc:
            error = exc.message
            summary = {"error": exc.message, "code": exc.code.value}
        except Exception as exc:  # noqa: BLE001
            logger.exception("QA tool %s failed", name)
            error = str(exc)
            summary = {"error": str(exc)}
        return {
            "tool": name,
            "args": args,
            "ok": error is None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "result": summary,
            "error": error,
        }

    async def _dispatch_tool(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        name: str,
        args: dict[str, Any],
        state: ToolLoopState,
        **ctx,
    ) -> Any:
        handlers = {
            "search_instances": self._tool_search_instances,
            "get_instance": self._tool_get_instance,
            "list_relations": self._tool_list_relations,
            "expand_hops": self._tool_expand_hops,
            "expand_neighbors": self._tool_expand_hops,
            "get_schema": self._tool_get_schema,
        }
        handler = handlers.get(name)
        if handler is None:
            return None
        if name == "get_schema":
            return await handler(session, ontology_model_id, state, **ctx)
        return await handler(session, ontology_model_id, args, state, **ctx)

    async def _tool_search_instances(
        self, session, ontology_model_id, args, state: ToolLoopState, **ctx
    ) -> dict[str, Any]:
        args.update(
            ground_search_args(args, ctx["class_labels"], ctx["question"])
        )
        args = await self._ensure_class_scope(
            ctx["provider"], args, ctx["class_labels"], ctx["question"]
        )
        query = str(args.get("q") or args.get("query") or "")
        listing = not query or is_list_question(ctx["question"])
        list_limit = 20 if listing else 8
        resp = await self.ks.search_instances(
            session,
            ontology_model_id,
            q=query,
            class_label=args.get("class_label"),
            class_id=args.get("class_id") if is_uuid_str(args.get("class_id")) else None,
            limit=clamp_limit(args.get("limit"), default=list_limit),
            caller=ctx["caller"],
            trace_id=ctx["trace_id"],
            session_id=ctx["session_id"],
        )
        resp, args = await self._retry_list_search(
            session, ontology_model_id, args, resp, ctx
        )
        state.last_ids = [hit.id for hit in resp.items[:5]]
        state.evidences.extend(resp.evidences)
        if resp.items:
            first = resp.items[0]
            state.focus["焦点"] = {
                "id": first.id,
                "label": first.label,
                "class_label": first.class_label,
            }
        return {
            "count": len(resp.items),
            "ids": state.last_ids[:5],
            "labels": [hit.label for hit in resp.items[:5]],
        }

    async def _retry_list_search(self, session, ontology_model_id, args, resp, ctx):
        need_retry = resp.empty_hit and not args.get("class_label") and is_list_question(
            ctx["question"]
        )
        if not need_retry:
            return resp, args
        query = str(args.get("q") or args.get("query") or "")
        retry_label = link_class_label(ctx["question"] or query, ctx["class_labels"])
        if not retry_label:
            retry_label = await self._link_class_via_llm(
                ctx["provider"], ctx["question"] or query, ctx["class_labels"]
            )
        if not retry_label:
            return resp, args
        resp = await self.ks.search_instances(
            session,
            ontology_model_id,
            q="",
            class_label=retry_label,
            limit=clamp_limit(args.get("limit"), default=20),
            caller=ctx["caller"],
            trace_id=ctx["trace_id"],
            session_id=ctx["session_id"],
        )
        args = {**args, "class_label": retry_label, "q": ""}
        return resp, args

    async def _tool_get_instance(
        self, session, ontology_model_id, args, state: ToolLoopState, **ctx
    ) -> dict[str, Any]:
        instance_id = str(
            args.get("instance_id") or args.get("id") or (state.last_ids[0] if state.last_ids else "")
        )
        if not instance_id:
            raise AppError(ErrorCode.VALIDATION_ERROR, message="缺少 instance_id")
        detail = await self.ks.get_instance(
            session,
            ontology_model_id,
            instance_id,
            caller=ctx["caller"],
            trace_id=ctx["trace_id"],
            session_id=ctx["session_id"],
        )
        state.last_ids = [detail.id]
        state.evidences.extend(detail.evidences)
        state.focus["焦点"] = {
            "id": detail.id,
            "label": detail.label,
            "class_label": detail.class_label,
        }
        return {"id": detail.id, "label": detail.label, "class_label": detail.class_label}

    async def _tool_list_relations(
        self, session, ontology_model_id, args, state: ToolLoopState, **ctx
    ) -> dict[str, Any]:
        instance_id = str(
            args.get("instance_id") or args.get("id") or (state.last_ids[0] if state.last_ids else "")
        )
        if not instance_id:
            raise AppError(ErrorCode.VALIDATION_ERROR, message="缺少 instance_id")
        rels = await self.ks.list_relations(
            session,
            ontology_model_id,
            instance_id,
            property_id=args.get("property_id") if is_uuid_str(args.get("property_id")) else None,
            property_label=args.get("property_label"),
            caller=ctx["caller"],
            trace_id=ctx["trace_id"],
            session_id=ctx["session_id"],
        )
        state.last_ids = [instance_id] + [rel.other_instance_id for rel in rels[:8]]
        for rel in rels[:12]:
            state.evidences.append(
                Evidence(
                    id="",
                    kind="relation",
                    entity_id=rel.other_instance_id,
                    label=rel.other_instance_label or rel.other_instance_id,
                    class_label=rel.other_class_label,
                    properties={"predicate": rel.property_label, "direction": rel.direction},
                )
            )
        return {"count": len(rels), "labels": [rel.other_instance_label for rel in rels[:8]]}

    async def _tool_expand_hops(
        self, session, ontology_model_id, args, state: ToolLoopState, **ctx
    ) -> dict[str, Any]:
        starts = args.get("start_ids") or state.last_ids[:3]
        if isinstance(starts, str):
            starts = [starts]
        hops = clamp_hops(args.get("max_hops") or 2)
        preds = args.get("predicates")
        if isinstance(preds, str):
            preds = [preds]
        whitelist = ctx.get("whitelist_preds") or set()
        if whitelist and preds:
            preds = [pred for pred in preds if pred in whitelist] or None
        resp = await self.ks.expand_hops(
            session,
            ontology_model_id,
            [str(item) for item in starts],
            max_hops=hops,
            max_nodes=clamp_nodes(args.get("max_nodes")),
            predicates=preds,
            caller=ctx["caller"],
            trace_id=ctx["trace_id"],
            session_id=ctx["session_id"],
        )
        state.last_ids = [node.id for node in resp.nodes[:8]]
        state.evidences.extend(resp.evidences)
        return {"nodes": len(resp.nodes), "links": len(resp.links), "truncated": resp.truncated}

    async def _tool_get_schema(
        self, session, ontology_model_id, state: ToolLoopState, **ctx
    ) -> dict[str, Any]:
        schema = await self.ks.get_schema(
            session, ontology_model_id, caller=ctx["caller"], trace_id=ctx["trace_id"]
        )
        state.evidences.append(
            Evidence(
                id="",
                kind="schema",
                entity_id=schema.ontology_model_id,
                label=schema.ontology_model_name,
                properties={
                    "class_count": len(schema.classes),
                    "property_count": len(schema.properties),
                },
            )
        )
        return {"classes": [cls.label for cls in schema.classes[:30]]}


def _initial_state(resolved: dict[str, Any]) -> ToolLoopState:
    state = ToolLoopState()
    focus_inst = {}
    if isinstance(resolved, dict):
        focus_inst = resolved.get("焦点") or resolved.get("focus") or {}
    if isinstance(focus_inst, dict) and focus_inst.get("id"):
        state.last_ids = [str(focus_inst["id"])]
    return state
