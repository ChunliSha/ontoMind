"""OpenAI-compatible LLM provider (cloud or local OpenAI-compatible API)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
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
from app.ai.prompts.business_logic_topology import TOPOLOGY_RETRY, TOPOLOGY_SYSTEM
from app.ai.prompts.schema_induction import SCHEMA_INDUCTION_RETRY, SCHEMA_INDUCTION_SYSTEM
from app.topology.logic_graph import LogicGraph, logic_graph_from_llm
from app.core.config import settings
from app.core.exceptions import AppError, ErrorCode

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_json_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    # 兜底：截取第一个 { 到最后一个 }
    if text and not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return text


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = _strip_json_fences(raw)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("模型返回的 JSON 不是对象")
    # 兼容常见错误嵌套：{"schema":{...}} / {"result":{...}} / {"data":{...}}
    for key in ("schema", "result", "data", "output"):
        nested = data.get(key)
        if isinstance(nested, dict) and ("classes" in nested or "properties" in nested):
            return nested
    return data


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

    async def _chat(
        self,
        system: str,
        user: str,
        *,
        timeout: float = 120.0,
        use_json_object: bool = True,
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
            "temperature": 0.2,
        }
        if use_json_object:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.api_base}/chat/completions", headers=headers, json=payload
            )
            # 部分本地网关不支持 response_format，降级重试
            if resp.status_code in (400, 422) and use_json_object:
                logger.warning("response_format unsupported, retry without it: %s", resp.text[:200])
                return await self._chat(system, user, timeout=timeout, use_json_object=False)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, list):
                # 部分兼容实现返回 content parts
                parts = []
                for p in content:
                    if isinstance(p, dict) and p.get("type") == "text":
                        parts.append(p.get("text") or "")
                    elif isinstance(p, str):
                        parts.append(p)
                content = "".join(parts)
            return str(content or "")

    async def induce_schema(
        self, texts: list[str], existing_classes: list[str]
    ) -> AIResult[SchemaInductionResult]:
        started = time.perf_counter()
        usable = [t.strip() for t in texts if t and t.strip()]
        if not usable:
            return AIResult(
                success=False,
                error="文档无可抽取文本（请确认非结构化文件已解析完成）",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        # 控制上下文长度，优先用靠前文档
        clipped: list[str] = []
        budget = 12000
        for t in usable[:5]:
            if budget <= 0:
                break
            chunk = t[:budget]
            clipped.append(chunk)
            budget -= len(chunk)

        user_msg = (
            f"已有类（请勿重复）：{existing_classes!r}\n\n"
            f"文档内容：\n" + "\n\n---\n\n".join(clipped)
        )

        last_error = "schema induction failed"
        messages_user = user_msg
        for attempt in range(3):
            try:
                system = SCHEMA_INDUCTION_SYSTEM if attempt == 0 else (
                    SCHEMA_INDUCTION_SYSTEM + "\n\n" + SCHEMA_INDUCTION_RETRY
                )
                if attempt > 0:
                    messages_user = (
                        f"{user_msg}\n\n上次错误：{last_error}\n请按契约重新输出。"
                    )
                raw = await self._chat(system, messages_user, timeout=180.0)
                data = _parse_json_object(raw)
                result = SchemaInductionResult.model_validate(data)
                if not result.classes:
                    last_error = "classes 为空，未归纳出任何本体类"
                    logger.warning(
                        "induce_schema empty classes (attempt %s): %s",
                        attempt + 1,
                        raw[:500],
                    )
                    continue
                return AIResult(
                    success=True,
                    result=result,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            except (ValidationError, json.JSONDecodeError, ValueError, KeyError, httpx.HTTPError) as exc:
                last_error = str(exc)
                logger.warning(
                    "induce_schema attempt %s failed: %s", attempt + 1, last_error
                )
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.exception("induce_schema unexpected error")
                break

        return AIResult(
            success=False,
            error=last_error,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def extract_instances(
        self,
        texts: list[str],
        schema_snapshot: SchemaSnapshot,
        task_id: uuid.UUID | None = None,
    ) -> AIResult[InstanceExtractionResult]:
        """Semantica pipeline (adapted from extract/populate_ontology.py)."""
        started = time.perf_counter()
        try:
            from app.ai.extract_job import run_extract_cancellable
            from app.ai.populate_ontology_pipeline import extract_instances_sync
            from app.tasks.runner import ExtractionCancelled

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
            data = _parse_json_object(raw)
            items = data.get("business_logic", data if isinstance(data, list) else [])
            rules = [BusinessLogicRuleDraft.model_validate(x) for x in items]
            return AIResult(
                success=True,
                result=rules,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
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
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        class_keys = list(catalog_by_class.keys())
        clipped_catalog: dict[str, list[dict[str, str]]] = {}
        for class_key, items in catalog_by_class.items():
            clipped_catalog[class_key] = [
                {"id": x.get("id", ""), "label": (x.get("label") or "")[:80]}
                for x in items[:80]
            ]
        user_msg = (
            f"本体类与候选实例（按类名分组，节点 type 使用类名，instance_ref 优先用 id）：\n"
            f"{json.dumps(clipped_catalog, ensure_ascii=False)}\n\n"
            f"文档内容：\n{chunk[:8000]}"
        )

        last_error = "business logic topology extraction failed"
        messages_user = user_msg
        for attempt in range(3):
            try:
                system = (
                    TOPOLOGY_SYSTEM
                    if attempt == 0
                    else TOPOLOGY_SYSTEM + "\n\n" + TOPOLOGY_RETRY
                )
                if attempt > 0:
                    messages_user = f"{user_msg}\n\n上次错误：{last_error}\n请按契约重新输出。"
                raw = await self._chat(system, messages_user, timeout=180.0)
                data = _parse_json_object(raw)
                graph = logic_graph_from_llm(data)
                if not graph.nodes:
                    last_error = "nodes 为空，未抽取出任何业务逻辑节点"
                    logger.warning(
                        "extract_business_logic_topology empty nodes (attempt %s): %s",
                        attempt + 1,
                        raw[:500],
                    )
                    continue
                return AIResult(
                    success=True,
                    result=graph,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            except (ValidationError, json.JSONDecodeError, ValueError, KeyError, httpx.HTTPError) as exc:
                last_error = str(exc)
                logger.warning(
                    "extract_business_logic_topology attempt %s failed: %s",
                    attempt + 1,
                    last_error,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.exception("extract_business_logic_topology unexpected error")
                break

        return AIResult(
            success=False,
            error=last_error,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
