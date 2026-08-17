"""LLM model management service."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.core.security import decrypt_password, encrypt_password
from app.models.llm import LlmModelConfig
from app.repositories.llm_model_repository import LlmModelRepository
from app.schemas.common import PageResponse
from app.schemas.llm import (
    LlmModelCreate,
    LlmModelRead,
    LlmModelTestResult,
    LlmModelUpdate,
    LlmPreset,
)
from app.services._utils import parse_uuid

logger = logging.getLogger(__name__)

PRESETS: list[LlmPreset] = [
    LlmPreset(
        id="openai",
        name="OpenAI",
        source="cloud",
        provider="openai",
        api_base="https://api.openai.com/v1",
        model_name="gpt-4o-mini",
        hint="官方 OpenAI Chat Completions API",
    ),
    LlmPreset(
        id="deepseek",
        name="DeepSeek",
        source="cloud",
        provider="deepseek",
        api_base="https://api.deepseek.com/v1",
        model_name="deepseek-chat",
        hint="DeepSeek 开放平台（OpenAI 兼容）",
    ),
    LlmPreset(
        id="qwen",
        name="通义千问",
        source="cloud",
        provider="qwen",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen-plus",
        hint="阿里云 DashScope OpenAI 兼容模式",
    ),
    LlmPreset(
        id="zhipu",
        name="智谱 GLM",
        source="cloud",
        provider="zhipu",
        api_base="https://open.bigmodel.cn/api/paas/v4",
        model_name="glm-4-flash",
        hint="智谱开放平台（OpenAI 兼容）",
    ),
    LlmPreset(
        id="moonshot",
        name="Moonshot / Kimi",
        source="cloud",
        provider="moonshot",
        api_base="https://api.moonshot.cn/v1",
        model_name="moonshot-v1-8k",
        hint="月之暗面 Moonshot API",
    ),
    LlmPreset(
        id="ollama",
        name="Ollama（本地）",
        source="local",
        provider="ollama",
        api_base="http://127.0.0.1:11434/v1",
        model_name="qwen2.5:7b",
        hint="本机或内网 Ollama，OpenAI 兼容端点 /v1",
    ),
    LlmPreset(
        id="vllm",
        name="vLLM / 本地 OpenAI 兼容",
        source="local",
        provider="vllm",
        api_base="http://127.0.0.1:8001/v1",
        model_name="default",
        hint="vLLM、LM Studio、LocalAI 等 OpenAI 兼容服务",
    ),
    LlmPreset(
        id="openlab_qwen35",
        name="OpenLab Qwen3 35B",
        source="local",
        provider="local_openai",
        api_base="http://172.24.116.1:8048/v1",
        model_name="qwen3_6_35B",
        hint="内网 OpenLab OpenAI 兼容服务；API Key 填 OpenLab_AI_API_Key_…（勿带 Bearer 前缀）",
    ),
]


def _to_read(obj: LlmModelConfig) -> LlmModelRead:
    return LlmModelRead(
        id=str(obj.id),
        name=obj.name,
        source=obj.source,  # type: ignore[arg-type]
        provider=obj.provider,  # type: ignore[arg-type]
        api_base=obj.api_base,
        has_api_key=bool(obj.api_key_enc),
        model_name=obj.model_name,
        is_default=obj.is_default,
        status=obj.status,  # type: ignore[arg-type]
        last_error=obj.last_error,
        last_tested_at=obj.last_tested_at,
        extra_config=obj.extra_config,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


class LlmModelService:
    def __init__(self) -> None:
        self.repo = LlmModelRepository()

    def presets(self) -> list[LlmPreset]:
        return list(PRESETS)

    async def list(
        self,
        session: AsyncSession,
        *,
        source: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PageResponse[LlmModelRead]:
        rows, total = await self.repo.list(
            session, source=source, status=status, page=page, page_size=page_size
        )
        return PageResponse(
            items=[_to_read(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_active(self, session: AsyncSession) -> list[LlmModelRead]:
        rows = await self.repo.list_active(session)
        return [_to_read(r) for r in rows]

    async def create(self, session: AsyncSession, body: LlmModelCreate) -> LlmModelRead:
        if await self.repo.get_by_name(session, body.name):
            raise AppError(ErrorCode.LLM_002, field="name")
        if body.provider != "mock" and not (body.api_base or "").strip():
            raise AppError(ErrorCode.VALIDATION_ERROR, message="请填写 API Base URL", field="api_base")
        if body.is_default:
            await self.repo.clear_default(session)
        obj = LlmModelConfig(
            name=body.name.strip(),
            source=body.source,
            provider=body.provider,
            api_base=(body.api_base or "").strip() or None,
            api_key_enc=encrypt_password(body.api_key) if body.api_key else None,
            model_name=body.model_name.strip(),
            is_default=body.is_default,
            status="active",
            extra_config=body.extra_config,
        )
        obj = await self.repo.create(session, obj)
        return _to_read(obj)

    async def update(self, session: AsyncSession, id: str, body: LlmModelUpdate) -> LlmModelRead:
        obj = await self._get(session, id)
        data = body.model_dump(exclude_unset=True)
        if "api_key" in data:
            key = data.pop("api_key")
            if key is None:
                pass
            elif key == "":
                obj.api_key_enc = None
            else:
                obj.api_key_enc = encrypt_password(key)
        if "name" in data and data["name"] and data["name"] != obj.name:
            clash = await self.repo.get_by_name(session, data["name"])
            if clash:
                raise AppError(ErrorCode.LLM_002, field="name")
        if data.get("is_default") is True:
            await self.repo.clear_default(session)
        for k, v in data.items():
            setattr(obj, k, v)
        obj.updated_at = datetime.now(timezone.utc)
        await self.repo.update(session, obj)
        return _to_read(obj)

    async def delete(self, session: AsyncSession, id: str) -> None:
        obj = await self._get(session, id)
        was_default = obj.is_default
        await self.repo.delete(session, obj)
        if was_default:
            # 若删的是默认，尝试把第一个 active 设为默认
            actives = await self.repo.list_active(session)
            if actives:
                actives[0].is_default = True
                await self.repo.update(session, actives[0])

    async def set_default(self, session: AsyncSession, id: str) -> LlmModelRead:
        obj = await self._get(session, id)
        if obj.status != "active":
            raise AppError(ErrorCode.CONFLICT, message="只能将启用中的模型设为默认")
        await self.repo.clear_default(session)
        obj.is_default = True
        obj.updated_at = datetime.now(timezone.utc)
        await self.repo.update(session, obj)
        return _to_read(obj)

    async def test_connection(self, session: AsyncSession, id: str) -> LlmModelTestResult:
        obj = await self._get(session, id)
        started = time.perf_counter()
        try:
            if obj.provider == "mock":
                latency = int((time.perf_counter() - started) * 1000)
                obj.status = "active"
                obj.last_error = None
                obj.last_tested_at = datetime.now(timezone.utc)
                await self.repo.update(session, obj)
                return LlmModelTestResult(ok=True, message="Mock 模型可用", latency_ms=latency)

            api_base = (obj.api_base or "").rstrip("/")
            if not api_base:
                raise AppError(ErrorCode.LLM_003, message="未配置 API Base")

            headers = {"Content-Type": "application/json"}
            if obj.api_key_enc:
                headers["Authorization"] = f"Bearer {decrypt_password(obj.api_key_enc)}"

            # 优先用 models 列表探测；不支持时回退 chat/completions
            async with httpx.AsyncClient(timeout=20.0) as client:
                models_url = f"{api_base}/models"
                resp = await client.get(models_url, headers=headers)
                if resp.status_code >= 400:
                    payload = {
                        "model": obj.model_name,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    }
                    resp = await client.post(
                        f"{api_base}/chat/completions", headers=headers, json=payload
                    )
                if resp.status_code >= 400:
                    raise AppError(
                        ErrorCode.LLM_003,
                        message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    )

            latency = int((time.perf_counter() - started) * 1000)
            obj.status = "active"
            obj.last_error = None
            obj.last_tested_at = datetime.now(timezone.utc)
            await self.repo.update(session, obj)
            return LlmModelTestResult(ok=True, message="连通性测试成功", latency_ms=latency)
        except AppError as exc:
            obj.status = "failed"
            obj.last_error = exc.message
            obj.last_tested_at = datetime.now(timezone.utc)
            await self.repo.update(session, obj)
            return LlmModelTestResult(ok=False, message=exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm test failed: %s", exc)
            msg = "模型连通性测试失败，请检查 API 地址、密钥与模型名"
            obj.status = "failed"
            obj.last_error = str(exc)[:500]
            obj.last_tested_at = datetime.now(timezone.utc)
            await self.repo.update(session, obj)
            return LlmModelTestResult(ok=False, message=msg)

    async def _get(self, session: AsyncSession, id: str) -> LlmModelConfig:
        obj = await self.repo.get_by_id(session, parse_uuid(id))
        if not obj:
            raise AppError(ErrorCode.LLM_001)
        return obj
