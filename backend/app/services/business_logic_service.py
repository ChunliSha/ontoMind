"""BusinessLogicService — list/export persisted rules (§8.6)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ErrorCode
from app.repositories.business_logic_repository import BusinessLogicRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.business_logic import BusinessLogicExport, BusinessLogicRuleRead
from app.services._utils import parse_uuid, uid


class BusinessLogicService:
    def __init__(self) -> None:
        self.repo = BusinessLogicRepository()
        self.task_repo = TaskRepository()

    async def list_by_schema(
        self, session: AsyncSession, schema_id: str
    ) -> list[BusinessLogicRuleRead]:
        rows = await self.repo.list_by_schema(session, parse_uuid(schema_id))
        return [self._to_read(r) for r in rows]

    async def list_by_task(
        self, session: AsyncSession, task_id: str
    ) -> list[BusinessLogicRuleRead]:
        task = await self.task_repo.get_by_id(session, parse_uuid(task_id))
        if not task:
            raise AppError(ErrorCode.TASK_001)
        rows = await self.repo.list_by_task(session, task.id)
        return [self._to_read(r) for r in rows]

    async def export(
        self, session: AsyncSession, schema_id: str
    ) -> BusinessLogicExport:
        rows = await self.list_by_schema(session, schema_id)
        items = []
        for i, r in enumerate(rows, start=1):
            item = {
                "rule_id": f"rule_{i:03d}",
                "type": r.rule_type,
                "description": r.description,
                "condition": r.condition,
            }
            if r.rule_type == "causality":
                item["consequence"] = r.consequence
            else:
                item["action_required"] = r.action_required
                item["severity"] = r.severity
            items.append(item)
        return BusinessLogicExport(business_logic=items)

    @staticmethod
    def _to_read(obj) -> BusinessLogicRuleRead:
        return BusinessLogicRuleRead(
            id=str(obj.id),
            schema_id=str(obj.schema_id),
            rule_type=obj.rule_type,
            description=obj.description,
            condition=obj.condition,
            consequence=obj.consequence,
            action_required=obj.action_required,
            severity=obj.severity,
            source_doc_id=uid(obj.source_doc_id),
            extraction_task_id=uid(obj.extraction_task_id),
            created_at=obj.created_at,
        )
