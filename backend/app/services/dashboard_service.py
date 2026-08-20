"""DashboardService — summary + recent activity (§8.8)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.class_repository import ClassRepository
from app.repositories.db_source_repository import DbSourceRepository
from app.repositories.file_repository import FileRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.schema_repository import SchemaRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.dashboard import ActivityItem, DashboardActivity, DashboardSummary


class DashboardService:
    def __init__(self) -> None:
        self.db_repo = DbSourceRepository()
        self.file_repo = FileRepository()
        self.schema_repo = SchemaRepository()
        self.class_repo = ClassRepository()
        self.instance_repo = InstanceRepository()
        self.task_repo = TaskRepository()

    async def summary(self, session: AsyncSession) -> DashboardSummary:
        structured = await self.db_repo.count_all(session)
        unstructured = await self.file_repo.count_all(session)
        schema_count = await self.schema_repo.count_all(session)
        class_count = await self.class_repo.count_all(session)
        instance_count = await self.instance_repo.count_all(session)
        published = await self.schema_repo.count_published(session)
        graph_versions = published or schema_count
        return DashboardSummary(
            data_source_count=structured + unstructured,
            structured_count=structured,
            unstructured_count=unstructured,
            schema_count=schema_count,
            class_count=class_count,
            instance_count=instance_count,
            graph_count=graph_versions,
            graph_version_count=graph_versions,
        )

    async def activity(self, session: AsyncSession, *, limit: int = 20) -> DashboardActivity:
        tasks = await self.task_repo.list_recent(session, limit=limit)
        items: list[ActivityItem] = []
        type_label = {
            "schema_induction": "Schema 抽取",
            "instance_unstructured": "非结构化实例抽取",
            "instance_structured": "结构化实例抽取",
            "business_logic": "业务逻辑抽取",
            "business_logic_topology": "业务逻辑抽取",
        }
        for t in tasks:
            items.append(
                ActivityItem(
                    id=str(t.id),
                    action=f"{type_label.get(t.task_type, t.task_type)} · {t.status}",
                    resource_type="extraction_task",
                    resource_id=str(t.id),
                    resource_name=t.task_type,
                    created_at=t.created_at,
                )
            )
        return DashboardActivity(items=items)
