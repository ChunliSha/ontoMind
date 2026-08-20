"""Unit tests for topology merge / grounding / layout / assemble / pipeline."""

from __future__ import annotations

from app.topology.assemble import assemble_topology
from app.topology.grounding import ground_logic_graph
from app.topology.index import IndexedClass, IndexedInstance, IndexedRelation, OntologyIndex
from app.topology.layout import layout_topology
from app.topology.logic_graph import LogicEdge, LogicGraph, LogicNode, logic_graph_from_llm
from app.topology.merge import merge_by_instance_id, merge_logic_graphs
from app.topology.node_types import LAYOUT_X_STEP, LAYOUT_Y_STEP, UNGROUNDED_OBJECT_ID
from app.topology.pipeline import build_from_logic, catalog_for_prompt


def _index() -> OntologyIndex:
    classes = [
        IndexedClass("c-op", "操作", local_name="Operation", instance_count=2),
        IndexedClass("c-fault", "故障", local_name="Fault", instance_count=1),
        IndexedClass("c-sug", "建议", local_name="Suggestion", instance_count=1),
    ]
    instances = [
        IndexedInstance(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1",
            class_id="c-op",
            class_label="操作",
            label="主站召测请求下发",
            local_name="DispatchMasterRequest",
            data_values={"接口名称": "主站召测请求报文是否成功下发", "请求方法": "POST"},
            relations=[
                IndexedRelation("关联设备", "dev-1", "主站"),
            ],
        ),
        IndexedInstance(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2",
            class_id="c-op",
            class_label="操作",
            label="主站侧日志是否完整",
            aliases=["检查主站日志完整性"],
        ),
        IndexedInstance(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3",
            class_id="c-fault",
            class_label="故障",
            label="主站任务过多来不及下发",
            data_values={"故障编码": "0010006"},
        ),
        IndexedInstance(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4",
            class_id="c-sug",
            class_label="建议",
            label="定界到主站，排查主站侧其他问题",
        ),
    ]
    return OntologyIndex(schema_id="s1", schema_version=1, classes=classes, instances=instances)


TYPE_MAP = {
    "业务操作": {"c-op"},
    "故障": {"c-fault"},
    "建议": {"c-sug"},
}


def test_logic_graph_from_llm_coerces_id_and_camel_case():
    graph = logic_graph_from_llm(
        {
            "result": {
                "name": "召测",
                "nodes": [
                    {
                        "id": "a",
                        "type": "业务操作",
                        "name": "主站召测请求下发",
                        "judgementContent": "是否下发成功",
                    }
                ],
                "links": [{"from": "a", "to": "a", "condition": "否"}],
            }
        }
    )
    assert graph.name == "召测"
    assert graph.nodes[0].key == "a"
    assert graph.nodes[0].label == "主站召测请求下发"
    assert graph.nodes[0].judgement_content == "是否下发成功"
    assert graph.edges[0].source == "a"
    assert graph.edges[0].label == "否"


def test_merge_logic_graphs_by_type_and_label():
    g1 = LogicGraph(
        name="chunk1",
        nodes=[
            LogicNode(key="n1", type="业务操作", label="主站召测请求下发", description="来自文档A"),
            LogicNode(key="n2", type="故障", label="主站任务过多来不及下发"),
        ],
        edges=[LogicEdge(source="n1", target="n2", label="否")],
    )
    g2 = LogicGraph(
        name="chunk2",
        nodes=[
            LogicNode(key="n1", type="业务操作", label="主站召测请求下发", judgement_content="是否成功"),
            LogicNode(key="n9", type="建议", label="定界到主站，排查主站侧其他问题"),
        ],
        edges=[LogicEdge(source="n1", target="n9", label="是")],
    )
    merged = merge_logic_graphs([g1, g2])
    assert len(merged.nodes) == 3
    op = next(n for n in merged.nodes if n.type == "业务操作")
    assert op.description == "来自文档A"
    assert op.judgement_content == "是否成功"
    assert len(merged.edges) == 2


def test_merge_by_instance_id_collapses_duplicates():
    graph = LogicGraph(
        nodes=[
            LogicNode(key="a", type="业务操作", label="A", instance_id="i1"),
            LogicNode(key="b", type="业务操作", label="A-alias", instance_id="i1", description="keep"),
            LogicNode(key="c", type="建议", label="C"),
        ],
        edges=[
            LogicEdge(source="a", target="c"),
            LogicEdge(source="b", target="c"),
        ],
    )
    merged = merge_by_instance_id(graph)
    assert len(merged.nodes) == 2
    assert len(merged.edges) == 1
    op = next(n for n in merged.nodes if n.instance_id == "i1")
    assert op.description == "keep"


def test_grounding_exact_and_unmatched():
    index = _index()
    graph = LogicGraph(
        nodes=[
            LogicNode(key="n1", type="业务操作", label="主站召测请求下发"),
            LogicNode(key="n2", type="故障", label="文档里才有的新故障"),
        ]
    )
    grounded = ground_logic_graph(graph, index, TYPE_MAP)
    assert grounded.nodes[0].instance_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
    assert grounded.nodes[0].matched_by == "exact"
    assert grounded.nodes[1].instance_id is None
    assert grounded.nodes[1].matched_by == "unmatched"


def test_assemble_grounds_and_keeps_custom():
    index = _index()
    nodes = [
        LogicNode(
            key="n1",
            type="业务操作",
            label="主站召测请求下发",
            instance_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1",
            judgement_content="是否下发成功",
        ),
        LogicNode(key="n2", type="故障", label="未知故障", description="文档描述"),
    ]
    graph, key_map = assemble_topology(nodes, [("n1", "n2", "否")], index, name="召测")
    assert graph.name == "召测"
    op = next(n for n in graph.nodes if n.type == "操作")
    fault = next(n for n in graph.nodes if n.label == "未知故障")
    assert op.properties["selectedObjectId"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
    assert op.properties.get("classLabel") == "操作"
    assert op.properties["judgementContent"] == "是否下发成功"
    assert fault.properties["selectedObjectId"] == UNGROUNDED_OBJECT_ID
    assert fault.properties["description"] == "文档描述"
    assert key_map["n1"] == op.id
    assert op.color


def test_layout_grid_and_ports():
    index = _index()
    nodes = [
        LogicNode(key="a", type="业务操作", label="A"),
        LogicNode(key="b", type="故障", label="B"),
        LogicNode(key="c", type="建议", label="C"),
    ]
    graph, _ = assemble_topology(nodes, [("a", "b", "否"), ("b", "c", "")], index)
    layout_topology(graph)
    ys = sorted(float(n.y) for n in graph.nodes)
    assert ys[1] - ys[0] == LAYOUT_Y_STEP
    assert ys[2] - ys[1] == LAYOUT_Y_STEP
    by_label = {n.label: n for n in graph.nodes}
    # Downward chain → bottom to top
    down = next(e for e in graph.edges if e.source.cell == by_label["A"].id)
    assert down.source.port == "port-bottom"
    assert down.target.port == "port-top"


def test_layout_locked_keeps_coordinates():
    index = _index()
    nodes = [LogicNode(key="a", type="建议", label="A")]
    graph, _ = assemble_topology(nodes, [], index)
    graph.nodes[0].x = 12
    graph.nodes[0].y = 34
    layout_topology(graph, locked=True)
    assert graph.nodes[0].x == 12
    assert graph.nodes[0].y == 34


def test_layout_with_cycle_terminates():
    index = _index()
    nodes = [
        LogicNode(key="a", type="业务操作", label="A"),
        LogicNode(key="b", type="故障", label="B"),
        LogicNode(key="c", type="建议", label="C"),
    ]
    graph, _ = assemble_topology(
        nodes,
        [("a", "b", "否"), ("b", "a", "回退"), ("a", "a", "自环"), ("b", "c", "")],
        index,
    )
    layout_topology(graph)
    assert len(graph.nodes) == 3
    assert all(n.x is not None and n.y is not None for n in graph.nodes)


def test_pipeline_build_from_logic():
    index = _index()
    logic = LogicGraph(
        name="召测诊断",
        nodes=[
            LogicNode(key="n1", type="业务操作", label="主站召测请求下发"),
            LogicNode(key="n2", type="故障", label="主站任务过多来不及下发"),
            LogicNode(key="n3", type="建议", label="定界到主站，排查主站侧其他问题"),
            LogicNode(key="n4", type="建议", label="文档独有建议"),
        ],
        edges=[
            LogicEdge(source="n1", target="n2", label="否"),
            LogicEdge(source="n2", target="n3", label="是"),
        ],
    )
    graph, warnings, stats = build_from_logic(logic, index, name="召测诊断")
    assert graph.name == "召测诊断"
    assert stats["node_count"] == 4
    assert stats["grounded"] == 3
    assert any(w["code"] == "ungrounded" for w in warnings)
    types = {n.type for n in graph.nodes}
    assert "操作" in types
    assert "故障" in types
    assert "建议" in types
    custom = next(n for n in graph.nodes if n.label == "文档独有建议")
    assert custom.properties["selectedObjectId"] == UNGROUNDED_OBJECT_ID


def test_catalog_groups_by_ontology_class():
    index = _index()
    catalog = catalog_for_prompt(index)
    assert set(catalog) == {"操作", "故障", "建议"}
    assert {x["label"] for x in catalog["操作"]} == {"主站召测请求下发", "主站侧日志是否完整"}
    assert catalog["故障"]


def test_extract_logic_graphs_merges_chunks():
    import asyncio

    from app.topology.pipeline import extract_logic_graphs

    async def fake(text: str, catalog):
        if "第二段" in text:
            return LogicGraph(
                nodes=[LogicNode(key="x", type="建议", label="定界到主站，排查主站侧其他问题")],
                edges=[],
            )
        return LogicGraph(
            nodes=[LogicNode(key="n1", type="业务操作", label="主站召测请求下发")],
            edges=[],
        )

    merged = asyncio.run(
        extract_logic_graphs(fake, ["第一段 主站召测", "第二段 建议"], {"业务操作": [], "建议": []})
    )
    assert {n.type for n in merged.nodes} == {"业务操作", "建议"}


def test_extract_logic_graphs_caps_chunks():
    import asyncio

    from app.topology.pipeline import extract_logic_graphs

    calls: list[str] = []

    async def fake(text: str, catalog):
        calls.append(text)
        return LogicGraph(
            nodes=[LogicNode(key=f"k{len(calls)}", type="操作", label=text[:12] or "n")],
            edges=[],
        )

    texts = [f"第{i}段 " + ("主站召测请求下发。" * 200) for i in range(12)]
    asyncio.run(extract_logic_graphs(fake, texts, {"操作": []}, max_chunks=3))
    assert len(calls) == 3
