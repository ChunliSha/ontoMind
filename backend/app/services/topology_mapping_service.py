"""Type-mapping suggestion and instance catalog for topology extraction."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.topology import (
    CatalogInstanceRead,
    InstanceCatalogResponse,
    TypeCatalogItemRead,
    TypeMappingCandidateRead,
    TypeMappingItemRead,
    TypeMappingSuggestResponse,
    UnmappedClassRead,
)
from app.services.topology_index_service import TopologyIndexService
from app.topology.type_mapping import suggest_type_mapping


class TopologyMappingService:
    def __init__(self) -> None:
        self.index_svc = TopologyIndexService()

    async def suggest(
        self,
        session: AsyncSession,
        schema_id: str,
        *,
        schema_version: int | None = None,
    ) -> TypeMappingSuggestResponse:
        index = await self.index_svc.build_index(
            session, schema_id, schema_version=schema_version
        )
        result = suggest_type_mapping(index)
        return TypeMappingSuggestResponse(
            schema_id=index.schema_id,
            schema_version=index.schema_version,
            instance_count=len(index.instances),
            mapping=[
                TypeMappingItemRead(
                    type_key=m.type_key,
                    class_ids=m.class_ids,
                    class_labels=m.class_labels,
                    instance_count=m.instance_count,
                    candidates=[
                        TypeMappingCandidateRead(
                            class_id=c.class_id,
                            class_label=c.class_label,
                            local_name=c.local_name,
                            instance_count=c.instance_count,
                            type_key=c.type_key,
                            score=c.score,
                            reasons=c.reasons,
                        )
                        for c in m.candidates
                    ],
                )
                for m in result.mapping
            ],
            unmapped_classes=[
                UnmappedClassRead(
                    class_id=c.id,
                    class_label=c.label,
                    local_name=c.local_name,
                    instance_count=c.instance_count,
                )
                for c in result.unmapped_classes
            ],
        )

    async def catalog(
        self,
        session: AsyncSession,
        schema_id: str,
        *,
        schema_version: int | None = None,
        per_type_limit: int = 200,
    ) -> InstanceCatalogResponse:
        index = await self.index_svc.build_index(
            session, schema_id, schema_version=schema_version
        )
        by_class = _catalog_by_class(index, per_type_limit)
        mapping_items = [
            TypeMappingItemRead(
                type_key=item.type_key,
                class_ids=item.class_ids,
                class_labels=[item.type_key],
                instance_count=len(item.instances),
            )
            for item in by_class
        ]
        return InstanceCatalogResponse(
            schema_id=index.schema_id,
            schema_version=index.schema_version,
            mapping=mapping_items,
            by_type=by_class,
            instances=_catalog_instances(index, max(per_type_limit * 4, 400)),
        )


def _catalog_instance(inst) -> CatalogInstanceRead:
    return CatalogInstanceRead(
        id=inst.id,
        label=inst.label,
        local_name=inst.local_name,
        class_id=inst.class_id,
        class_label=inst.class_label,
    )


def _label_of(item) -> str:
    return item.label


def _catalog_by_class(index, per_type_limit: int) -> list[TypeCatalogItemRead]:
    by_class: list[TypeCatalogItemRead] = []
    for cls in sorted(index.classes.values(), key=_label_of):
        insts = [_catalog_instance(item) for item in index.instances_for_class(cls.id)]
        insts.sort(key=_label_of)
        by_class.append(
            TypeCatalogItemRead(
                type_key=cls.label,
                class_ids=[cls.id],
                instances=insts[:per_type_limit],
            )
        )
    return by_class


def _catalog_instances(index, cap: int) -> list[CatalogInstanceRead]:
    rows = [_catalog_instance(item) for item in index.instances.values()]
    rows.sort(key=_label_of)
    return rows[:cap]
