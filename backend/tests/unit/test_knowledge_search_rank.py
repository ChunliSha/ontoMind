"""Power-domain instance ranking (1号主变压器)."""

from app.knowledge.search_rank import score_hit


def test_exact_transformer_label_ranks_highest():
    q = "1号主变压器"
    exact = score_hit(q, label="1号主变压器", class_label="变压器")
    partial = score_hit(q, label="2号主变压器", class_label="变压器")
    other = score_hit(q, label="滨江220kV变电站", class_label="变电站")
    assert exact == 1.0
    assert exact > partial
    assert exact > other


def test_alias_in_data_value():
    score = score_hit(
        "主变",
        label="1号主变压器",
        data_values={"设备编号": "T1", "别名": "1号主变"},
    )
    assert score >= 0.7


def test_empty_query_scores_zero():
    assert score_hit("", label="1号主变压器") == 0.0
