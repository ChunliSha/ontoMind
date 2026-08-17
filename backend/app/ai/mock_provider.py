"""Mock LLM provider — returns UCD demo data (设备/产线/供应商)."""

from __future__ import annotations

import asyncio
import random
import time

from app.ai.base import (
    AIResult,
    BusinessLogicRuleDraft,
    ExtractedDataValue,
    ExtractedInstance,
    ExtractedRelation,
    InducedClass,
    InducedProperty,
    InstanceExtractionResult,
    SchemaInductionResult,
    SchemaSnapshot,
)


class MockLLMProvider:
    async def induce_schema(
        self, texts: list[str], existing_classes: list[str]
    ) -> AIResult[SchemaInductionResult]:
        started = time.perf_counter()
        await asyncio.sleep(random.uniform(0.3, 0.9))
        existing = set(existing_classes)
        classes = [
            InducedClass(label="设备", local_name="Equipment", description="工业设备", confidence=92),
            InducedClass(label="产线", local_name="ProductionLine", description="生产线", confidence=90),
            InducedClass(label="供应商", local_name="Supplier", description="设备供应商", confidence=88),
        ]
        classes = [c for c in classes if c.label not in existing]
        properties = [
            InducedProperty(
                class_label="设备",
                label="设备编号",
                kind="data",
                datatype="xsd:string",
                required=True,
                confidence=95,
            ),
            InducedProperty(
                class_label="设备",
                label="运行状态",
                kind="data",
                datatype="xsd:string",
                confidence=90,
            ),
            InducedProperty(
                class_label="设备",
                label="投运日期",
                kind="data",
                datatype="xsd:dateTime",
                confidence=85,
            ),
            InducedProperty(
                class_label="设备",
                label="属于产线",
                kind="object",
                range_class_label="产线",
                confidence=93,
            ),
            InducedProperty(
                class_label="产线",
                label="产线名称",
                kind="data",
                datatype="xsd:string",
                required=True,
                confidence=91,
            ),
            InducedProperty(
                class_label="供应商",
                label="供应商名称",
                kind="data",
                datatype="xsd:string",
                required=True,
                confidence=89,
            ),
        ]
        latency = int((time.perf_counter() - started) * 1000)
        return AIResult(
            success=True,
            result=SchemaInductionResult(classes=classes, properties=properties),
            confidence=90,
            tokens_used=1200,
            latency_ms=latency,
        )

    async def extract_instances(
        self, texts: list[str], schema_snapshot: SchemaSnapshot
    ) -> AIResult[InstanceExtractionResult]:
        started = time.perf_counter()
        await asyncio.sleep(random.uniform(0.3, 0.9))
        class_labels = {c.label for c in schema_snapshot.classes} or {"设备", "产线"}
        instances: list[ExtractedInstance] = []
        if "产线" in class_labels or not schema_snapshot.classes:
            instances.append(
                ExtractedInstance(
                    class_label="产线",
                    label="一号产线",
                    local_name="Line_01",
                    confidence=91,
                    data_values=[ExtractedDataValue(property_label="产线名称", value="一号产线")],
                )
            )
        if "设备" in class_labels or not schema_snapshot.classes:
            instances.append(
                ExtractedInstance(
                    class_label="设备",
                    label="GY-01",
                    local_name="GY-01",
                    confidence=94,
                    data_values=[
                        ExtractedDataValue(property_label="设备编号", value="GY-01"),
                        ExtractedDataValue(property_label="运行状态", value="运行中"),
                        ExtractedDataValue(property_label="投运日期", value="2024-01-15"),
                    ],
                    relations=[
                        ExtractedRelation(property_label="属于产线", target_instance_label="一号产线")
                    ],
                )
            )
            instances.append(
                ExtractedInstance(
                    class_label="设备",
                    label="主变压器",
                    local_name="MainTransformer",
                    confidence=88,
                    data_values=[
                        ExtractedDataValue(property_label="设备编号", value="TR-001"),
                        ExtractedDataValue(property_label="运行状态", value="告警"),
                    ],
                )
            )
        if "供应商" in class_labels:
            instances.append(
                ExtractedInstance(
                    class_label="供应商",
                    label="华能电气",
                    local_name="HuaNeng",
                    confidence=86,
                    data_values=[
                        ExtractedDataValue(property_label="供应商名称", value="华能电气")
                    ],
                )
            )
        latency = int((time.perf_counter() - started) * 1000)
        return AIResult(
            success=True,
            result=InstanceExtractionResult(instances=instances),
            confidence=90,
            tokens_used=800,
            latency_ms=latency,
        )

    async def extract_business_logic(
        self,
        texts: list[str],
        schema_snapshot: SchemaSnapshot,
        instance_labels: list[str],
    ) -> AIResult[list[BusinessLogicRuleDraft]]:
        started = time.perf_counter()
        await asyncio.sleep(random.uniform(0.3, 0.9))
        subject = instance_labels[0] if instance_labels else "主变压器"
        rules = [
            BusinessLogicRuleDraft(
                rule_id="rule_001",
                type="causality",
                description=f"当{subject}油温超过85度时，可能导致绝缘老化加速，引发轻瓦斯报警。",
                condition={
                    "subject": subject,
                    "attribute": "油温",
                    "operator": ">",
                    "value": "85℃",
                },
                consequence=["绝缘老化加速", "轻瓦斯报警"],
                source_doc="断路器异常跳闸分析报告.docx",
            ),
            BusinessLogicRuleDraft(
                rule_id="rule_002",
                type="constraint",
                description="断路器SF6气体压力低于0.4MPa时，必须立即闭锁分合闸操作。",
                condition={
                    "subject": "断路器",
                    "attribute": "SF6气体压力",
                    "operator": "<",
                    "value": "0.4MPa",
                },
                action_required="闭锁分合闸操作",
                severity="critical",
                source_doc="2026年Q1变压器检修工单.pdf",
            ),
        ]
        latency = int((time.perf_counter() - started) * 1000)
        return AIResult(
            success=True,
            result=rules,
            confidence=87,
            tokens_used=600,
            latency_ms=latency,
        )
