"""Golden-set metric helpers."""

from app.eval import load_golden_set, score_trace, summarize


def test_golden_set_loaded():
    items = load_golden_set()
    ids = {i["id"] for i in items}
    assert "q-lookup-transformer" in ids
    assert "q-chitchat" in ids


def test_score_lookup_pass():
    item = {
        "id": "q-lookup-transformer",
        "intent": "lookup_entity",
        "must_tools": ["search_instances"],
        "entity_labels": ["1号主变压器"],
        "empty_ok": False,
    }
    trace = {
        "intent": "lookup_entity",
        "tool_trace": [{"tool": "search_instances"}],
        "evidences": [{"id": "E1", "label": "1号主变压器"}],
        "answer": "1号主变压器是一台主变 [E1]。",
    }
    row = score_trace(item, trace)
    assert row["passed"]
    assert row["citation_cover"] > 0


def test_honest_empty_required():
    item = {
        "id": "q-missing",
        "intent": "lookup_entity",
        "must_tools": ["search_instances"],
        "empty_ok": True,
        "require_honest_empty": True,
    }
    bad = score_trace(
        item,
        {
            "intent": "lookup_entity",
            "tool_trace": [{"tool": "search_instances"}],
            "evidences": [],
            "answer": "电压等级是 1000kV。",
        },
    )
    good = score_trace(
        item,
        {
            "intent": "lookup_entity",
            "tool_trace": [{"tool": "search_instances"}],
            "evidences": [],
            "answer": "知识库中未找到相关信息。",
        },
    )
    assert not bad["passed"]
    assert good["passed"]


def test_summarize():
    rows = [{"passed": True, "intent_ok": True, "tool_ok": True, "citation_cover": 1, "empty_hit": False}]
    s = summarize(rows)
    assert s["accuracy"] == 1.0
    assert s["tool_success"] == 1.0
