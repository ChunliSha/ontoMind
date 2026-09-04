"""Pure helpers that keep ExtractionService methods short and low-complexity."""

from __future__ import annotations

import uuid

from app.ai.base import ExtractedInstance
from app.ai.populate_ontology_pipeline import instance_merge_key
from app.models.schema import OntologyClass, OntologyProperty

LABEL_PROPERTY_NAMES = {"姓名", "名称", "客户名称", "name", "full_name"}


def is_human_label_property(prop: OntologyProperty | None) -> bool:
    if prop is None:
        return False
    is_data = prop.kind == "data"
    named = prop.label in LABEL_PROPERTY_NAMES
    return is_data and named


def label_source_columns(prop_bindings, props: dict) -> list[str]:
    cols: list[str] = []
    for binding in prop_bindings:
        pid = binding.target_property_id
        if not pid:
            continue
        if is_human_label_property(props.get(pid)):
            cols.append(binding.source_column)
    return cols


def display_label_from_row(row: dict, uri_local: str, label_cols: list[str]) -> str:
    for col in label_cols:
        val = row.get(col)
        if val is not None and str(val).strip():
            return str(val).strip()
    return uri_local


def mapped_data_property_ids(prop_bindings, props: dict) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for binding in prop_bindings:
        pid = binding.target_property_id
        if not pid:
            continue
        prop = props.get(pid)
        if prop is not None and prop.kind == "data":
            ids.append(prop.id)
    return ids


def merge_extracted_instance(
    merged: dict[tuple[str, str], ExtractedInstance],
    inst: ExtractedInstance,
) -> None:
    key = instance_merge_key(inst.class_label, inst.label)
    existing = merged.get(key)
    if existing is None:
        merged[key] = inst
        return
    if (inst.confidence or 0) > (existing.confidence or 0):
        existing.confidence = inst.confidence
    _merge_data_values(existing, inst)
    _merge_relations(existing, inst)


def _merge_data_values(existing: ExtractedInstance, inst: ExtractedInstance) -> None:
    seen = {(item.property_label, item.value) for item in existing.data_values}
    for data_val in inst.data_values:
        pair = (data_val.property_label, data_val.value)
        if pair in seen:
            continue
        existing.data_values.append(data_val)
        seen.add(pair)


def _merge_relations(existing: ExtractedInstance, inst: ExtractedInstance) -> None:
    seen = {
        (rel.property_label, rel.target_instance_label) for rel in existing.relations
    }
    for rel in inst.relations:
        pair = (rel.property_label, rel.target_instance_label)
        if pair in seen:
            continue
        existing.relations.append(rel)
        seen.add(pair)


def index_classes_by_name(classes_list: list[OntologyClass]) -> dict[str, OntologyClass]:
    classes: dict[str, OntologyClass] = {}
    for cls in classes_list:
        classes[cls.label] = cls
        if cls.local_name:
            classes[cls.local_name] = cls
    return classes


def index_props_by_class(
    props: list[OntologyProperty],
) -> dict[uuid.UUID, dict[str, OntologyProperty]]:
    props_by_class: dict[uuid.UUID, dict[str, OntologyProperty]] = {}
    for prop in props:
        bucket = props_by_class.setdefault(prop.domain_class_id, {})
        bucket[prop.label] = prop
        if prop.local_name:
            bucket[prop.local_name] = prop
    return props_by_class
