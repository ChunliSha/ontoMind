"""Schema-constrained query-planning agent over KnowledgeService."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai import resolve_llm_provider
from app.ai.json_util import parse_json_object
from app.ai.openai_compatible_provider import OpenAICompatibleProvider
from app.core.config import settings
from app.core.exceptions import AppError, ErrorCode
from app.knowledge.access_log import log_access
from app.knowledge.class_link import is_list_question, link_class_label
from app.knowledge.evidence import Evidence, number_evidences
from app.knowledge.service import KnowledgeService
from app.models.knowledge import QaMessage, QaSession
from app.qa.prompts import (
    CLASS_LINK_SYSTEM,
    GENERATE_SYSTEM,
    PLAN_SYSTEM,
    class_link_user_prompt,
    generate_user_prompt,
    plan_user_prompt,
)
from app.qa.tool_loop import QaToolMixin
from app.schemas.common import PageResponse
from app.schemas.qa import QaChatResponse, QaMessageRead, QaSessionRead, QaSessionSummary
from app.services._utils import parse_uuid, uid

logger = logging.getLogger(__name__)

ALLOWED_TOOLS = {
    "search_instances",
    "get_instance",
    "list_relations",
    "expand_hops",
    "expand_neighbors",
    "get_schema",
}
ALLOWED_INTENTS = {
    "lookup_entity",
    "ask_attribute",
    "ask_relation",
    "multi_hop",
    "schema_explain",
    "chitchat_reject",
}

EMPTY_ANSWER = "知识库中未找到相关信息。"


@dataclass
class ChatPrep:
    obj: QaSession
    query: str
    provider: OpenAICompatibleProvider
    schema: Any
    plan: dict[str, Any]
    intent: str
    caller: str
    trace: str
    started: float


class QaAgent(QaToolMixin):
    def __init__(self) -> None:
        self.ks = KnowledgeService()

    async def create_session(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        model_id: str | None = None,
        *,
        source: str = "qa",
    ) -> QaSessionRead:
        sl = await self.ks.resolve_slice(session, ontology_model_id)
        llm_id = parse_uuid(model_id) if model_id else None
        src = (source or "qa").strip()[:16] or "qa"
        obj = QaSession(
            ontology_model_id=sl.model.id,
            llm_model_id=llm_id,
            title="",
            source=src,
            resolved_entities={},
        )
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return self._session_read(obj, [])

    async def get_session(self, session: AsyncSession, session_id: str) -> QaSessionRead:
        obj = await self._load_session(session, session_id)
        return self._session_read(obj, list(obj.messages or []))

    async def list_sessions(
        self,
        session: AsyncSession,
        *,
        ontology_model_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PageResponse[QaSessionSummary]:
        filt = [QaSession.source != "mcp"]
        if ontology_model_id:
            filt.append(QaSession.ontology_model_id == parse_uuid(ontology_model_id, field="ontology_model_id"))
        count_stmt = select(func.count()).select_from(QaSession)
        if filt:
            count_stmt = count_stmt.where(*filt)
        total = int((await session.execute(count_stmt)).scalar_one() or 0)
        msg_n = (
            select(QaMessage.session_id, func.count().label("n"))
            .group_by(QaMessage.session_id)
            .subquery()
        )
        stmt = select(QaSession, func.coalesce(msg_n.c.n, 0)).outerjoin(
            msg_n, msg_n.c.session_id == QaSession.id
        )
        if filt:
            stmt = stmt.where(*filt)
        stmt = (
            stmt.order_by(QaSession.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await session.execute(stmt)).all()
        items = [
            QaSessionSummary(
                id=str(obj.id),
                ontology_model_id=str(obj.ontology_model_id),
                llm_model_id=uid(obj.llm_model_id),
                title=(obj.title or "").strip() or "新会话",
                message_count=int(n or 0),
                created_at=obj.created_at,
                updated_at=obj.updated_at,
            )
            for obj, n in rows
        ]
        return PageResponse(items=items, total=total, page=page, page_size=page_size)

    async def update_session(
        self, session: AsyncSession, session_id: str, *, title: str
    ) -> QaSessionRead:
        obj = await self._load_session(session, session_id)
        obj.title = title.strip()[:80]
        await session.flush()
        return self._session_read(obj, list(obj.messages or []))

    async def delete_session(self, session: AsyncSession, session_id: str) -> None:
        obj = await self._load_session(session, session_id)
        await session.execute(delete(QaMessage).where(QaMessage.session_id == obj.id))
        await session.delete(obj)
        await session.flush()

    async def chat(
        self,
        session: AsyncSession,
        session_id: str,
        question: str,
        *,
        model_id: str | None = None,
        caller: str = "qa",
        trace_id: str = "",
    ) -> QaChatResponse:
        prep = await self._begin_chat(
            session, session_id, question, model_id=model_id, caller=caller, trace_id=trace_id
        )
        user_msg = QaMessage(session_id=prep.obj.id, role="user", content=prep.query)
        session.add(user_msg)
        await session.flush()
        answer, evidences, tool_trace = await self._answer_from_plan(session, prep)
        return await self._commit_chat(session, prep, answer, evidences, tool_trace, model_id)

    async def _begin_chat(
        self,
        session: AsyncSession,
        session_id: str,
        question: str,
        *,
        model_id: str | None,
        caller: str,
        trace_id: str,
    ) -> ChatPrep:
        obj = await self._load_session(session, session_id)
        query = (question or "").strip()
        if not query:
            raise AppError(ErrorCode.VALIDATION_ERROR, message="请输入问题", field="question")
        started = time.perf_counter()
        ontology_model_id = str(obj.ontology_model_id)
        trace = trace_id or uuid.uuid4().hex[:16]
        llm_model_id = model_id or uid(obj.llm_model_id)
        provider = await resolve_llm_provider(session, llm_model_id)
        if not isinstance(provider, OpenAICompatibleProvider):
            raise AppError(ErrorCode.LLM_003, message="当前模型不支持知识问答")
        schema = await self.ks.get_schema(
            session, ontology_model_id, caller=caller, trace_id=trace
        )
        plan = await self._plan(
            provider,
            question=query,
            schema_summary=self._schema_summary(schema.model_dump()),
            history=self._history_text(list(obj.messages or [])[-8:]),
            resolved_entities=json.dumps(obj.resolved_entities or {}, ensure_ascii=False),
        )
        intent = plan.get("intent") if isinstance(plan.get("intent"), str) else "lookup_entity"
        if intent not in ALLOWED_INTENTS:
            intent = "lookup_entity"
        plan["intent"] = intent
        return ChatPrep(
            obj=obj,
            query=query,
            provider=provider,
            schema=schema,
            plan=plan,
            intent=intent,
            caller=caller,
            trace=trace,
            started=started,
        )

    async def _answer_from_plan(self, session, prep: ChatPrep):
        if prep.intent == "chitchat_reject":
            answer = "该问题与当前本体知识无关，我只能根据已绑定的本体模型回答事实问题。"
            return answer, [], []
        evidences, tool_trace, focus = await self._run_tools(
            session,
            str(prep.obj.ontology_model_id),
            prep.plan,
            prep.obj.resolved_entities or {},
            provider=prep.provider,
            class_labels=[cls.label for cls in prep.schema.classes],
            question=prep.query,
            caller=prep.caller,
            trace_id=prep.trace,
            session_id=str(prep.obj.id),
        )
        if focus:
            merged = dict(prep.obj.resolved_entities or {})
            merged.update(focus)
            prep.obj.resolved_entities = merged
        empty = len(evidences) == 0
        tools_failed = bool(tool_trace) and all(not item.get("ok") for item in tool_trace)
        if empty and tools_failed:
            return "检索未能完成，请稍后重试。", evidences, tool_trace
        answer = await self._generate(
            prep.provider,
            question=prep.query,
            plan=prep.plan,
            evidences=evidences,
            empty=empty,
        )
        if empty and "未找到" not in answer and "没有" not in answer:
            answer = EMPTY_ANSWER
        return answer, evidences, tool_trace

    async def _commit_chat(
        self,
        session,
        prep: ChatPrep,
        answer,
        evidences,
        tool_trace,
        model_id,
    ) -> QaChatResponse:
        evidences = number_evidences(evidences)
        session.add(
            QaMessage(
                session_id=prep.obj.id,
                role="assistant",
                content=answer,
                evidences=[item.model_dump() for item in evidences],
                plan=prep.plan,
                tool_trace=tool_trace,
            )
        )
        if not prep.obj.title:
            prep.obj.title = prep.query[:80]
        llm_model_id = model_id or uid(prep.obj.llm_model_id)
        if llm_model_id:
            try:
                prep.obj.llm_model_id = parse_uuid(llm_model_id)
            except AppError:
                logger.warning("invalid llm_model_id on QA session: %s", llm_model_id)
        await session.flush()
        await log_access(
            session,
            caller=prep.caller,
            tool_name="ask_knowledge",
            ontology_model_id=prep.obj.ontology_model_id,
            session_id=prep.obj.id,
            trace_id=prep.trace,
            plan=prep.plan,
            latency_ms=int((time.perf_counter() - prep.started) * 1000),
            empty_hit=len(evidences) == 0,
            request_meta={"intent": prep.intent, "tool_steps": len(tool_trace)},
        )
        return QaChatResponse(
            session_id=str(prep.obj.id),
            answer=answer,
            evidences=evidences,
            plan=prep.plan,
            tool_trace=tool_trace,
            resolved_entities=prep.obj.resolved_entities,
        )

    async def ask_direct(
        self,
        session: AsyncSession,
        ontology_model_id: str,
        question: str,
        *,
        model_id: str | None = None,
        caller: str = "mcp",
        trace_id: str = "",
    ) -> QaChatResponse:
        created = await self.create_session(
            session, ontology_model_id, model_id=model_id, source="mcp"
        )
        return await self.chat(
            session,
            created.id,
            question,
            model_id=model_id,
            caller=caller,
            trace_id=trace_id,
        )

    async def _plan(
        self,
        provider: OpenAICompatibleProvider,
        *,
        question: str,
        schema_summary: str,
        history: str,
        resolved_entities: str,
    ) -> dict[str, Any]:
        user = plan_user_prompt(
            question=question,
            schema_summary=schema_summary,
            history=history,
            resolved_entities=resolved_entities,
        )
        raw = await provider.chat(
            PLAN_SYSTEM,
            user,
            timeout=min(45.0, float(settings.QA_TIMEOUT_S)),
            use_json_object=True,
            temperature=0.1,
        )
        try:
            data = parse_json_object(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("QA plan JSON parse failed: %s", raw[:300])
            data = {
                "intent": "lookup_entity",
                "focus_labels": [question[:40]],
                "tools": [{"name": "search_instances", "args": {"q": question[:80], "limit": 10}}],
            }
        data["tools"] = _normalize_plan_tools(data.get("tools"), question)
        if data.get("intent") == "schema_explain" and not any(
            item["name"] == "get_schema" for item in data["tools"]
        ):
            data["tools"] = [{"name": "get_schema", "args": {}}] + data["tools"]
        if data.get("intent") == "lookup_entity" and not data["tools"]:
            data["tools"] = [{"name": "search_instances", "args": {"q": question[:80], "limit": 10}}]
        return data

    async def _generate(
        self,
        provider: OpenAICompatibleProvider,
        *,
        question: str,
        plan: dict[str, Any],
        evidences: list[Evidence],
        empty: bool,
    ) -> str:
        payload = [e.model_dump() for e in evidences[:24]]
        user = generate_user_prompt(
            question=question,
            plan=plan,
            evidences_json=json.dumps(payload, ensure_ascii=False)[:12000],
            empty=empty,
        )
        text = await provider.chat(
            GENERATE_SYSTEM,
            user,
            timeout=min(45.0, float(settings.QA_TIMEOUT_S)),
            use_json_object=False,
            temperature=0.15,
        )
        return (text or "").strip() or (EMPTY_ANSWER if empty else "（模型未返回回答）")

    async def _load_session(self, session: AsyncSession, session_id: str) -> QaSession:
        result = await session.execute(
            select(QaSession)
            .where(QaSession.id == parse_uuid(session_id, field="id"))
            .options(selectinload(QaSession.messages))
        )
        obj = result.scalar_one_or_none()
        if not obj:
            raise AppError(ErrorCode.NOT_FOUND, message="问答会话不存在")
        return obj

    def _object_property_labels_from_plan(self, plan: dict[str, Any]) -> set[str]:
        # filled after schema load inside tools; keep empty here
        return set()

    async def _ensure_class_scope(
        self,
        provider: OpenAICompatibleProvider | None,
        args: dict[str, Any],
        class_labels: list[str],
        question: str,
    ) -> dict[str, Any]:
        """If this is a type-listing question, bind class_label from Schema (string then LLM)."""
        out = dict(args)
        cl = str(out.get("class_label") or "").strip()
        if cl in class_labels:
            if is_list_question(question):
                out["q"] = ""
            return out
        q = str(out.get("q") or out.get("query") or "").strip()
        if not is_list_question(question) and not is_list_question(q):
            return out
        picked = await self._link_class_via_llm(provider, question or q, class_labels)
        if picked:
            out["class_label"] = picked
            out["q"] = ""
        return out

    async def _link_class_via_llm(
        self,
        provider: OpenAICompatibleProvider | None,
        question: str,
        class_labels: list[str],
    ) -> str | None:
        if not provider or not question.strip() or not class_labels:
            return None
        user = class_link_user_prompt(question=question.strip(), class_labels=class_labels)
        try:
            raw = await provider.chat(
                CLASS_LINK_SYSTEM,
                user,
                timeout=min(20.0, float(settings.QA_TIMEOUT_S)),
                use_json_object=True,
                temperature=0.0,
            )
            data = parse_json_object(raw)
        except Exception:  # noqa: BLE001
            logger.warning("QA class-link JSON parse failed")
            return None
        lab = data.get("class_label") if isinstance(data, dict) else None
        if lab is None or lab is False:
            return None
        if isinstance(lab, str):
            needle = lab.strip()
            if not needle or needle.lower() in {"null", "none", "nil"}:
                return None
            if needle in class_labels:
                return needle
            return link_class_label(needle, class_labels)
        return None

    def _schema_summary(self, schema: dict[str, Any]) -> str:
        lines = [f"模型: {schema.get('ontology_model_name')} v{schema.get('schema_version')}"]
        lines.append("类: " + "、".join(c.get("label") or "" for c in schema.get("classes") or [])[:800])
        op = [p for p in schema.get("properties") or [] if p.get("kind") == "object"]
        dp = [p for p in schema.get("properties") or [] if p.get("kind") == "data"]
        lines.append(
            "对象属性: "
            + "、".join(
                f"{p.get('label')}({p.get('domain_class_label')}→{p.get('range_class_label')})" for p in op[:40]
            )
        )
        lines.append("数据属性: " + "、".join(str(p.get("label")) for p in dp[:50]))
        return "\n".join(lines)

    def _history_text(self, messages: list[QaMessage]) -> str:
        parts = []
        for m in messages:
            role = "用户" if m.role == "user" else "助手"
            parts.append(f"{role}: {m.content[:300]}")
        return "\n".join(parts)

    def _session_read(self, obj: QaSession, messages: list[QaMessage]) -> QaSessionRead:
        return QaSessionRead(
            id=str(obj.id),
            ontology_model_id=str(obj.ontology_model_id),
            llm_model_id=uid(obj.llm_model_id),
            title=obj.title or "",
            resolved_entities=obj.resolved_entities,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            messages=[
                QaMessageRead(
                    id=str(m.id),
                    role=m.role,
                    content=m.content,
                    evidences=_evidence_list(m.evidences),
                    plan=m.plan,
                    tool_trace=list(m.tool_trace or []),
                    created_at=m.created_at,
                )
                for m in messages
            ],
        )

def _normalize_plan_tools(tools: Any, question: str) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        tools = []
    cleaned: list[dict[str, Any]] = []
    for item in tools[: int(settings.QA_MAX_TOOL_STEPS)]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name == "expand_neighbors":
            name = "expand_hops"
        if name not in ALLOWED_TOOLS:
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        cleaned.append({"name": name, "args": args})
    return cleaned


def _evidence_list(raw: Any) -> list[Evidence]:
    out: list[Evidence] = []
    for item in raw or []:
        try:
            out.append(Evidence.model_validate(item))
        except (TypeError, ValueError) as exc:
            logger.warning("skip invalid evidence payload: %s", exc)
    return out
