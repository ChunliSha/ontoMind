"""E2E: reflect customer_manager, map to 客户经理, run structured extraction."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db.session import AsyncSessionLocal
from app.models.schema import OntologyProperty
from app.rdf.ttl_builder import label_to_local_name
from app.repositories.class_repository import ClassRepository
from app.repositories.db_source_repository import DbSourceRepository
from app.repositories.instance_repository import InstanceRepository
from app.repositories.property_repository import PropertyRepository
from app.repositories.schema_repository import SchemaRepository
from app.repositories.table_repository import TableRepository
from app.schemas.data_source import TableSelectionPatch
from app.schemas.extraction import StructuredExtractionRequest
from app.schemas.mapping import MappingBindingCreate, MappingCreate
from app.services.db_source_service import DbSourceService
from app.services.extraction_service import ExtractionService
from app.services.mapping_service import MappingService


SCHEMA_NAME = "corporate_credit_risk_ontology"
CLASS_LABEL = "客户经理"
DS_HOST_HINT = "172.24.116.1"
TABLE_NAME = "customer_manager"

# column -> ontology property label on CreditOfficer / inherited Person
FIELD_MAP = {
    "manager_id": "工号",
    "full_name": "姓名",
    "phone": "联系电话",
    "branch_name": "所属分行",
    "job_title": "职级",
    "hire_date": "入职日期",
    "status": "在职状态",
}

EXTRA_PROPS = [
    ("所属分行", "xsd:string"),
    ("职级", "xsd:string"),
    ("入职日期", "xsd:dateTime"),
    ("在职状态", "xsd:string"),
]


async def ensure_credit_officer_props(session, schema_id, class_id) -> dict[str, str]:
    """Ensure CreditOfficer has mappable data properties; return label->id."""
    prop_repo = PropertyRepository()
    class_repo = ClassRepository()
    cls = await class_repo.get_by_id(session, class_id)
    assert cls

    # Collect inherited + own
    labels_seen: dict[str, OntologyProperty] = {}
    cur = cls
    while cur:
        for p in await prop_repo.list_by_class(session, cur.id):
            labels_seen.setdefault(p.label, p)
        if not cur.parent_class_id:
            break
        cur = await class_repo.get_by_id(session, cur.parent_class_id)

    needed = set(FIELD_MAP.values())
    for label, datatype in EXTRA_PROPS:
        if label not in labels_seen:
            p = OntologyProperty(
                schema_id=schema_id,
                domain_class_id=class_id,
                label=label,
                local_name=label_to_local_name(label),
                kind="data",
                datatype=datatype,
                source="manual",
            )
            p = await prop_repo.create(session, p)
            labels_seen[label] = p
            print(f"  + added property {label} on {CLASS_LABEL}")

    missing = needed - set(labels_seen)
    if missing:
        # Create missing Person-like props directly on CreditOfficer
        for label in sorted(missing):
            p = OntologyProperty(
                schema_id=schema_id,
                domain_class_id=class_id,
                label=label,
                local_name=label_to_local_name(label),
                kind="data",
                datatype="xsd:string",
                source="manual",
            )
            p = await prop_repo.create(session, p)
            labels_seen[label] = p
            print(f"  + added missing property {label} on {CLASS_LABEL}")

    await session.commit()
    return {lab: str(p.id) for lab, p in labels_seen.items() if lab in needed}


async def main() -> None:
    schema_repo = SchemaRepository()
    class_repo = ClassRepository()
    db_repo = DbSourceRepository()
    table_repo = TableRepository()
    instance_repo = InstanceRepository()
    db_svc = DbSourceService()
    map_svc = MappingService()
    ext_svc = ExtractionService()

    async with AsyncSessionLocal() as session:
        schemas, _ = await schema_repo.list(session, page=1, page_size=100)
        schema = next((s for s in schemas if s.name == SCHEMA_NAME), None)
        if not schema:
            raise SystemExit(f"schema {SCHEMA_NAME!r} not found")
        print(f"schema={schema.name} id={schema.id} ver={schema.version} status={schema.status}")

        classes = await class_repo.list_by_schema(session, schema.id)
        cls = next((c for c in classes if c.label == CLASS_LABEL), None)
        if not cls:
            raise SystemExit(f"class {CLASS_LABEL!r} not found")
        print(f"class={cls.label} id={cls.id} local={cls.local_name}")

        prop_ids = await ensure_credit_officer_props(session, schema.id, cls.id)
        print("mappable props:", prop_ids)

        sources, _ = await db_repo.list(session, page=1, page_size=50)
        ds = next((d for d in sources if d.host == DS_HOST_HINT), None) or (
            sources[0] if sources else None
        )
        if not ds:
            raise SystemExit("no data source found")
        print(f"datasource={ds.name} id={ds.id} host={ds.host} status={ds.status}")

        # Reflect tables
        tables = await db_svc.list_tables(session, str(ds.id))
        await session.commit()
        cm = next((t for t in tables if t.table_name == TABLE_NAME), None)
        if not cm:
            raise SystemExit(f"table {TABLE_NAME} not reflected; tables={[t.table_name for t in tables]}")
        print(f"table={cm.table_schema}.{cm.table_name} id={cm.id} cols={cm.column_count}")

        # Select for modeling
        selected = [t.id for t in tables if t.selected_for_modeling or t.id == cm.id]
        if cm.id not in selected:
            selected.append(cm.id)
        await db_svc.patch_selection(
            session, str(ds.id), TableSelectionPatch(selected_table_ids=selected)
        )
        await session.commit()
        print("selected_for_modeling: ok")

        # Target props via service (tests inheritance)
        targets = await map_svc.target_properties(session, str(cls.id))
        print("target_properties:", [(t.label, t.target_kind, t.id) for t in targets])

        bindings = [
            MappingBindingCreate(target_kind="instance_uri", source_column="manager_id"),
        ]
        label_to_prop = {t.label: t for t in targets if t.target_kind == "property"}
        for col, plabel in FIELD_MAP.items():
            tp = label_to_prop.get(plabel)
            if not tp or not tp.id:
                raise SystemExit(f"target property missing for {plabel}")
            bindings.append(
                MappingBindingCreate(
                    target_kind="property",
                    target_property_id=tp.id,
                    source_column=col,
                )
            )

        mapping = await map_svc.save(
            session,
            MappingCreate(
                schema_id=str(schema.id),
                class_id=str(cls.id),
                table_id=cm.id,
                bindings=bindings,
            ),
        )
        await session.commit()
        print(f"mapping id={mapping.id} bindings={len(mapping.bindings)}")

        before = await instance_repo.count_for_class(session, cls.id)
        print(f"CreditOfficer instances before={before}")

        accepted = await ext_svc.run_structured(
            session,
            StructuredExtractionRequest(
                schema_id=str(schema.id),
                mapping_ids=[mapping.id],
            ),
        )
        print(f"task accepted: {accepted.task_id}")
        schema_id = schema.id
        class_id = cls.id

    # Poll task
    task_id = accepted.task_id
    task = None
    for _ in range(60):
        async with AsyncSessionLocal() as session:
            task = await ext_svc.get_task(session, task_id)
            print(
                f"  status={task.status} progress={task.progress} "
                f"summary={task.output_summary} err={task.error_message}"
            )
            if task.status in ("succeeded", "failed", "cancelled"):
                break
        time.sleep(0.5)
    else:
        raise SystemExit("task timeout")

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        from app.models.instance import InstanceDataValue, OntologyInstance
        from app.models.schema import OntologyProperty

        result = await session.execute(
            select(OntologyInstance).where(
                OntologyInstance.schema_id == schema_id,
                OntologyInstance.class_id == class_id,
                OntologyInstance.source_type == "structured_mapping",
            )
        )
        rows = list(result.scalars().all())
        print(f"structured CreditOfficer instances: {len(rows)}")
        prop_rows = await session.execute(
            select(OntologyProperty).where(OntologyProperty.schema_id == schema_id)
        )
        prop_label = {p.id: p.label for p in prop_rows.scalars().all()}
        for inst in sorted(rows, key=lambda x: x.local_name or x.label):
            dvs = await session.execute(
                select(InstanceDataValue).where(InstanceDataValue.instance_id == inst.id)
            )
            vals = {
                prop_label.get(v.property_id, str(v.property_id)): v.value
                for v in dvs.scalars().all()
            }
            print(
                f"  label={inst.label!r} local={inst.local_name!r} "
                f"ver={inst.schema_version} values={vals}"
            )

        assert task is not None
        if task.status != "succeeded":
            raise SystemExit(f"E2E FAILED: task={task.status} {task.error_message}")
        if len(rows) < 6:
            raise SystemExit(f"E2E FAILED: expected >=6 instances, got {len(rows)}")
        named = [r for r in rows if r.label and not str(r.label).startswith("CM")]
        if len(named) < 6:
            raise SystemExit(
                f"E2E FAILED: expected human labels from 姓名, got {[r.label for r in rows]}"
            )
        if any(r.schema_version is None for r in rows):
            raise SystemExit("E2E FAILED: schema_version not set on instances")
        print("E2E OK")


if __name__ == "__main__":
    asyncio.run(main())
