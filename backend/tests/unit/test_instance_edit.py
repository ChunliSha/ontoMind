"""Instance edit: class clear, property kind checks, cascade delete."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppError
from app.schemas.extraction import InstanceDataValueWrite, InstanceRelationWrite
from app.services.instance_edit_service import InstanceEditService


def _svc() -> InstanceEditService:
    svc = InstanceEditService()
    svc.instance_repo = MagicMock()
    svc.relation_repo = MagicMock()
    svc.class_repo = MagicMock()
    svc.prop_repo = MagicMock()
    svc.schema_repo = MagicMock()
    svc._reader = MagicMock()
    svc.schema_repo.invalidate_graph_cache = AsyncMock()
    svc.relation_repo.delete_incident = AsyncMock()
    svc.relation_repo.replace_outgoing = AsyncMock()
    svc.instance_repo.delete = AsyncMock()
    svc.instance_repo.replace_data_values = AsyncMock()
    svc.instance_repo.get_by_id = AsyncMock()
    svc.class_repo.get_by_id = AsyncMock()
    svc.prop_repo.get_by_id = AsyncMock()
    svc._reader.get_instance = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_set_class_clears_when_empty():
    svc = _svc()
    inst = SimpleNamespace(schema_id=uuid.uuid4(), class_id=uuid.uuid4())
    session = AsyncMock()
    await svc._set_class(session, inst, "  ")
    assert inst.class_id is None
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_set_class_rejects_foreign_schema():
    svc = _svc()
    schema_id = uuid.uuid4()
    inst = SimpleNamespace(schema_id=schema_id, class_id=None)
    other = SimpleNamespace(id=uuid.uuid4(), schema_id=uuid.uuid4())
    svc.class_repo.get_by_id = AsyncMock(return_value=other)
    with pytest.raises(AppError):
        await svc._set_class(AsyncMock(), inst, str(other.id))


@pytest.mark.asyncio
async def test_data_property_rejects_object_kind():
    svc = _svc()
    schema_id = uuid.uuid4()
    inst = SimpleNamespace(id=uuid.uuid4(), schema_id=schema_id)
    prop = SimpleNamespace(id=uuid.uuid4(), schema_id=schema_id, kind="object", label="关联", multi=False)
    svc.prop_repo.get_by_id = AsyncMock(return_value=prop)
    with pytest.raises(AppError):
        await svc._replace_data_values(
            AsyncMock(),
            inst,
            [InstanceDataValueWrite(property_id=str(prop.id), value="x")],
        )


@pytest.mark.asyncio
async def test_target_must_belong_to_same_schema():
    svc = _svc()
    schema_id = uuid.uuid4()
    inst = SimpleNamespace(id=uuid.uuid4(), schema_id=schema_id)
    prop = SimpleNamespace(id=uuid.uuid4(), schema_id=schema_id, kind="object", label="关联", multi=True)
    svc.prop_repo.get_by_id = AsyncMock(return_value=prop)
    svc.instance_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=uuid.uuid4(), schema_id=uuid.uuid4())
    )
    with pytest.raises(AppError):
        await svc._replace_relations(
            AsyncMock(),
            inst,
            [InstanceRelationWrite(property_id=str(prop.id), object_instance_id=str(uuid.uuid4()))],
        )


@pytest.mark.asyncio
async def test_delete_instance_drops_incident_relations():
    svc = _svc()
    inst = SimpleNamespace(id=uuid.uuid4(), schema_id=uuid.uuid4())
    svc.instance_repo.get_by_id = AsyncMock(return_value=inst)
    await svc.delete_instance(AsyncMock(), str(inst.id))
    svc.relation_repo.delete_incident.assert_awaited()
    svc.instance_repo.delete.assert_awaited()
    svc.schema_repo.invalidate_graph_cache.assert_awaited()
