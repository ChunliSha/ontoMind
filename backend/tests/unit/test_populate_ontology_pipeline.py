"""Unit tests for populate_ontology_pipeline (no LLM calls)."""

from __future__ import annotations

from app.ai.base import SchemaSnapshot, SchemaSnapshotClass, SchemaSnapshotProperty
from app.ai.populate_ontology_pipeline import (
    graph_to_extracted,
    is_value_grounded_in_text,
    map_instances,
    schema_snapshot_to_ontology,
)


def test_schema_snapshot_to_ontology():
    snap = SchemaSnapshot(
        classes=[
            SchemaSnapshotClass(
                label="变压器",
                local_name="Transformer",
                properties=[
                    SchemaSnapshotProperty(
                        label="额定电压", kind="data", local_name="ratedVoltage"
                    ),
                    SchemaSnapshotProperty(
                        label="位于", kind="object", local_name="locatedAt"
                    ),
                ],
            )
        ]
    )
    onto = schema_snapshot_to_ontology(snap)
    assert onto["classes"]["Transformer"] == "变压器"
    assert onto["data_props"]["ratedVoltage"] == "额定电压"
    assert onto["object_props"]["locatedAt"] == "位于"


def test_is_value_grounded_in_text():
    text = "发现日期为2026年7月31日，编号QX-2026-0731。"
    assert is_value_grounded_in_text("2026-07-31", text)
    assert is_value_grounded_in_text("QX-2026-0731", text)
    assert not is_value_grounded_in_text("虚构编码ABC-999", text)


def test_graph_to_extracted_uses_chinese_labels():
    ontology = {
        "classes": {"Transformer": "变压器"},
        "object_props": {"locatedAt": "位于"},
        "data_props": {"ratedVoltage": "额定电压"},
    }

    class _Ent:
        def __init__(self, text: str, label: str, confidence: float = 0.9) -> None:
            self.text = text
            self.label = label
            self.confidence = confidence

    instances = map_instances([[_Ent("1号主变压器", "Transformer")]], ontology)
    assert len(instances) == 1
    inst = next(iter(instances.values()))
    graph_data = {
        "entities": [
            {
                "id": inst["id"],
                "text": inst["text"],
                "type": inst["type"],
                "class_local": inst["class_local"],
                "confidence": inst["confidence"],
            }
        ],
        "relationships": [],
    }
    extracted = graph_to_extracted(graph_data, [], ontology)
    assert len(extracted) == 1
    assert extracted[0].class_label == "变压器"
    assert extracted[0].label == "1号主变压器"
    assert extracted[0].confidence == 90.0
