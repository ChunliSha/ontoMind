"""OpenAI-compatible LLM provider (cloud or local OpenAI-compatible API)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import httpx
from pydantic import ValidationError

from app.ai.base import (
    AIResult,
    BusinessLogicRuleDraft,
    InstanceExtractionResult,
    SchemaInductionResult,
    SchemaSnapshot,
)
from app.ai.extract_job import run_extract_cancellable
from app.ai.json_util import parse_json_object
from app.ai.populate_ontology_pipeline import extract_instances_sync
from app.ai.prompts.business_logic_topology import (
    catalog_type_instruction,
    render_topology_retry,
    render_topology_system,
)
from app.ai.prompts.schema_induction import SCHEMA_INDUCTION_RETRY, SCHEMA_INDUCTION_SYSTEM
from app.core.config import settings
from app.core.exceptions import AppError, ErrorCode
from app.tasks.runner import ExtractionCancelled
from app.topology.logic_graph import LogicGraph, logic_graph_from_llm

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    """OpenAI-compatible Chat Completions client (cloud or local)."""

    def __init__(
        self,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_base = (api_base or settings.LLM_API_BASE or "").rstrip("/")
        self.api_key = api_key if api_key is not None else settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL or "gpt-4o-mini"

    def _ensure_configured(self) -> None:
        if not self.api_base:
            raise AppError(
                ErrorCode.LLM_003,
                message="未配置 API Base，请在模型管理中填写服务地址",
            )

    async def chat(
        self,
        system: str,
        user: str,
        *,
        timeout: float = 120.0,
        use_json_object: bool = True,
        temperature: float = 0.2,
    ) -> str:
        """Public chat-completions helper used by extraction and knowledge QA."""
        return await self._chat(
            system,
            user,
            timeout=timeout,
            use_json_object=use_json_object,
            temperature=temperature,
        )

    async def _chat(
        self,
        system: str,
        user: str,
        *,
        timeout: float = 120.0,
        use_json_object: bool = True,
        temperature: float = 0.2,
    ) -> str:
        self._ensure_configured()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if use_json_object:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.api_base}/chat/completions", headers=headers, json=payload
            )
            if resp.status_code in (400, 422) and use_json_object:
                logger.warning("response_format unsupported, retry without it: %s", resp.text[:200])
                return await self._chat(
                    system,
                    user,
                    timeout=timeout,
                    use_json_object=False,
                    temperature=temperature,
                )
            resp.raise_for_status()
            return _message_text(resp.json())

    @staticmethod
    def _clip_texts(usable: list[str], budget: int = 12000, max_docs: int = 5) -> list[str]:
        clipped: list[str] = []
        remain = budget
        for text in usable[:max_docs]:
            if remain <= 0:
                break
            chunk = text[:remain]
            clipped.append(chunk)
            remain -= len(chunk)
        return clipped

    @staticmethod
    def _latency_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    async def _json_attempts(self, system: str, retry_suffix: str, user_msg: str, timeout: float, parse_ok):
        last_error = "request failed"
        messages_user = user_msg
        for attempt in range(3):
            try:
                sys_prompt = system if attempt == 0 else f"{system}\n\n{retry_suffix}"
                if attempt > 0:
                    messages_user = f"{user_msg}\n\n上次错误：{last_error}\n请按契约重新输出。"
                raw = await self._chat(sys_prompt, messages_user, timeout=timeout)
                data = parse_json_object(raw)
                result, err = parse_ok(data, raw, attempt)
                if err:
                    last_error = err
                    continue
                return result, None
            except (ValidationError, json.JSONDecodeError, ValueError, KeyError, httpx.HTTPError) as exc:
                last_error = str(exc)
                logger.warning("llm json attempt %s failed: %s", attempt + 1, last_error)
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.exception("llm json unexpected error")
                break
        return None, last_error

    @staticmethod
    def _parse_schema(data, raw, attempt):
        result = SchemaInductionResult.model_validate(data)
        if result.classes:
            return result, None
        logger.warning("induce_schema empty classes (attempt %s): %s", attempt + 1, raw[:500])
        return None, "classes 为空，未归纳出任何本体类"

    @staticmethod
    def _parse_topology(data, raw, attempt):
        graph = logic_graph_from_llm(data)
        if graph.nodes:
            return graph, None
        logger.warning(
            "extract_business_logic_topology empty nodes (attempt %s): %s",
            attempt + 1,
            raw[:500],
        )
        return None, "nodes 为空，未抽取出任何业务逻辑节点"

    async def induce_schema(
        self, texts: list[str], existing_classes: list[str]
    ) -> AIResult[SchemaInductionResult]:
        started = time.perf_counter()
        usable = [t.strip() for t in texts if t and t.strip()]
        if not usable:
            return AIResult(
                success=False,
                error="文档无可抽取文本（请确认非结构化文件已解析完成）",
                latency_ms=self._latency_ms(started),
            )
        user_msg = (
            f"已有类（请勿重复）：{existing_classes!r}\n\n"
            f"文档内容：\n" + "\n\n---\n\n".join(self._clip_texts(usable))
        )
        result, last_error = await self._json_attempts(
            SCHEMA_INDUCTION_SYSTEM,
            SCHEMA_INDUCTION_RETRY,
            user_msg,
            180.0,
            self._parse_schema,
        )
        if result is not None:
            return AIResult(success=True, result=result, latency_ms=self._latency_ms(started))
        return AIResult(success=False, error=last_error, latency_ms=self._latency_ms(started))

    async def extract_instances(
        self,
        texts: list[str],
        schema_snapshot: SchemaSnapshot,
        task_id: uuid.UUID | None = None,
    ) -> AIResult[InstanceExtractionResult]:
        """Semantica pipeline (adapted from extract/populate_ontology.py)."""
        started = time.perf_counter()
        try:
            kwargs = {
                "provider": "openai",
                "llm_model": self.model,
                "api_key": self.api_key or None,
                "base_url": self.api_base or None,
            }
            if task_id is not None:
                result = await asyncio.to_thread(
                    run_extract_cancellable, task_id, texts, schema_snapshot, **kwargs
                )
            else:
                result = await asyncio.to_thread(extract_instances_sync, texts, schema_snapshot, **kwargs)
            if not result.instances:
                return AIResult(
                    success=False,
                    error="未抽取到可对齐本体的实例（请检查文档内容与 Schema）",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            return AIResult(
                success=True,
                result=result,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except ExtractionCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("extract_instances failed")
            return AIResult(
                success=False,
                error=str(exc),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

    async def extract_business_logic(
        self,
        texts: list[str],
        schema_snapshot: SchemaSnapshot,
        instance_labels: list[str],
    ) -> AIResult[list[BusinessLogicRuleDraft]]:
        started = time.perf_counter()
        try:
            raw = await self._chat(
                "You extract business logic rules as JSON array under key business_logic.",
                f"texts={texts[:3]!r}\ninstances={instance_labels!r}",
            )
            data = parse_json_object(raw)
            items = data.get("business_logic", data if isinstance(data, list) else [])
            rules = [BusinessLogicRuleDraft.model_validate(x) for x in items]
            return AIResult(
                success=True,
                result=rules,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("extract_business_logic failed")
            return AIResult(
                success=False,
                error=str(exc),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

    async def extract_business_logic_topology(
        self,
        text: str,
        catalog_by_class: dict[str, list[dict[str, str]]],
    ) -> AIResult[LogicGraph]:
        started = time.perf_counter()
        chunk = (text or "").strip()
        if not chunk:
            return AIResult(
                success=False,
                error="文档无可抽取文本",
                latency_ms=self._latency_ms(started),
            )
        clipped_catalog = _clip_catalog(catalog_by_class)
        user_msg = (
            "本体类与候选实例（按类名分组）。"
            f"{catalog_type_instruction(clipped_catalog)}\n"
            f"{json.dumps(clipped_catalog, ensure_ascii=False)}\n\n"
            f"文档内容：\n{chunk[:8000]}"
        )
        result, last_error = await self._json_attempts(
            render_topology_system(clipped_catalog),
            render_topology_retry(clipped_catalog),
            user_msg,
            180.0,
            self._parse_topology,
        )
        if result is not None:
            return AIResult(success=True, result=result, latency_ms=self._latency_ms(started))
        return AIResult(success=False, error=last_error, latency_ms=self._latency_ms(started))


def _message_text(data: dict[str, Any]) -> str:
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, list):
        return str(content or "")
    parts = [_part_text(part) for part in content]
    return str("".join(parts) or "")


def _part_text(part: Any) -> str:
    if isinstance(part, dict) and part.get("type") == "text":
        return part.get("text") or ""
    if isinstance(part, str):
        return part
    return ""


def _clip_catalog(catalog_by_class: dict[str, list[dict[str, str]]]) -> dict[str, list[dict[str, str]]]:
    clipped: dict[str, list[dict[str, str]]] = {}
    for class_key, items in catalog_by_class.items():
        clipped[class_key] = [
            {"id": item.get("id", ""), "label": (item.get("label") or "")[:80]}
            for item in items[:80]
        ]
    return clipped
