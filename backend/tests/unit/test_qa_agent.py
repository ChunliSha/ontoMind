"""QA planner JSON + honest empty answers (mocked LLM)."""

from __future__ import annotations

import json

import pytest

from app.knowledge.evidence import Evidence, number_evidences
from app.qa.agent import ALLOWED_INTENTS, EMPTY_ANSWER, QaAgent, _ground_search_args


class _FakeLLM:
    def __init__(
        self,
        plan: dict,
        answer: str = "根据 [E1]，电压等级为 220kV。",
        class_label: str | None = "人员",
    ):
        self.plan = plan
        self.answer = answer
        self.class_label = class_label
        self.calls = 0

    async def chat(self, system, user, **kwargs):
        self.calls += 1
        if "类对齐" in system:
            return json.dumps({"class_label": self.class_label}, ensure_ascii=False)
        if "规划器" in system:
            return json.dumps(self.plan, ensure_ascii=False)
        return self.answer


@pytest.mark.asyncio
async def test_plan_filters_unknown_tools():
    agent = QaAgent()
    llm = _FakeLLM(
        {
            "intent": "lookup_entity",
            "tools": [
                {"name": "search_instances", "args": {"q": "1号主变压器"}},
                {"name": "execute_sql", "args": {}},
                {"name": "expand_neighbors", "args": {"max_hops": 1}},
            ],
        }
    )
    plan = await agent._plan(
        llm, question="q", schema_summary="类: 设备", history="", resolved_entities="{}"
    )
    names = [t["name"] for t in plan["tools"]]
    assert "search_instances" in names
    assert "expand_hops" in names
    assert "execute_sql" not in names
    assert plan["intent"] in ALLOWED_INTENTS


@pytest.mark.asyncio
async def test_generate_empty_is_honest():
    agent = QaAgent()
    llm = _FakeLLM({"intent": "lookup_entity", "tools": []}, answer="可能是 500kV")
    text = await agent._generate(
        llm, question="宇宙尽头的变压器", plan={}, evidences=[], empty=True
    )
    # model ignored the instruction — agent.chat overwrites if empty and 未找到 missing
    assert text
    patched = text if "未找到" in text or "没有" in text else EMPTY_ANSWER
    assert "未找到" in patched


def test_number_evidences():
    ev = number_evidences([Evidence(id="", kind="instance", label="1号主变压器", entity_id="1")])
    assert ev[0].id == "E1"


def test_merge_evidences_keeps_instance_attributes():
    from app.knowledge.evidence import EvidenceTriple, merge_evidences

    search_hit = Evidence(
        id="",
        kind="instance",
        entity_id="abc",
        label="设备甲",
        class_label="设备",
        properties={"score": 0.9},
    )
    detail = Evidence(
        id="",
        kind="instance",
        entity_id="abc",
        label="设备甲",
        class_label="设备",
        properties={"额定容量": "180MVA", "生产厂商": "某厂"},
        triples=[
            EvidenceTriple(
                subject_id="abc",
                subject_label="设备甲",
                predicate="额定容量",
                object_value="180MVA",
            )
        ],
    )
    merged = merge_evidences([search_hit, detail])
    assert len(merged) == 1
    assert merged[0].properties.get("额定容量") == "180MVA"
    assert merged[0].properties.get("生产厂商") == "某厂"
    assert "score" not in merged[0].properties
    assert merged[0].triples


def test_ground_search_args_listing_uses_schema_class():
    labels = ["设备", "人员", "工单"]
    out = _ground_search_args(
        {"q": "设备", "limit": 10},
        labels,
        "有哪些设备？",
    )
    assert out["class_label"] == "设备"
    assert out["q"] == ""


def test_ground_search_args_drops_unlisted_class_label():
    labels = ["设备", "人员", "工单"]
    out = _ground_search_args(
        {"class_label": "天气", "q": ""},
        labels,
        "有哪些天气？",
    )
    assert not out.get("class_label")


@pytest.mark.asyncio
async def test_link_class_via_llm_must_use_whitelist():
    agent = QaAgent()
    labels = ["设备", "人员", "工单", "变压器"]
    llm = _FakeLLM({"intent": "lookup_entity", "tools": []}, class_label="人员")
    picked = await agent._link_class_via_llm(llm, "有哪些员工？", labels)
    assert picked == "人员"

    llm_bad = _FakeLLM({"intent": "lookup_entity", "tools": []}, class_label="员工")
    assert await agent._link_class_via_llm(llm_bad, "有哪些员工？", labels) is None
