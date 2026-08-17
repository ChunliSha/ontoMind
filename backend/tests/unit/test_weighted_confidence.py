"""Weighted entity confidence (entity_types re-score)."""

from __future__ import annotations

from app.ai.schema_grounded_instance import (
    _EntityHit,
    calculate_weighted_confidence,
    rescore_entities,
    type_similarity,
)


def test_type_similarity_exact_and_paren_form():
    types = ["Transformer (变压器)", "Defect (缺陷)"]
    assert type_similarity("Transformer", types) == 1.0
    assert type_similarity("变压器", types) == 1.0
    assert type_similarity("Transformer (变压器)", types) == 1.0


def test_weighted_formula_with_entity_types():
    # model=0.8, label exact → sim=1.0 → final = 0.5*0.8 + 0.5*1.0 = 0.9
    score = calculate_weighted_confidence(
        model_confidence=0.8,
        item_label="Transformer",
        item_text="1号主变",
        entity_types=["Transformer (变压器)"],
    )
    assert abs(score - 0.9) < 1e-6


def test_weighted_skips_when_no_entity_types():
    assert (
        calculate_weighted_confidence(
            model_confidence=0.66,
            item_label="Foo",
            item_text="bar",
            entity_types=None,
        )
        == 0.66
    )


def test_rescore_filters_below_threshold():
    types = ["Transformer (变压器)"]
    # model=0.5, poor type match → likely < 0.7
    kept = rescore_entities(
        [
            _EntityHit(text="1号主变", label="Transformer", confidence=0.95),
            _EntityHit(text="无关词", label="UnknownTypeXYZ", confidence=0.5),
        ],
        types,
        threshold=0.7,
    )
    assert any(e.label == "Transformer" for e in kept)
    assert all(e.confidence >= 0.7 for e in kept)
    assert not any(e.label == "UnknownTypeXYZ" for e in kept)
