"""Prompts for schema-constrained knowledge QA (intent, plan, generate)."""

from __future__ import annotations

import json

PLAN_SYSTEM = """你是 KnowMind 知识问答规划器。知识只存在于指定本体模型的 Schema 与实例中。
你必须输出 JSON 对象，不要输出其它文字。

允许的 intent：
- lookup_entity：查找某个实体
- ask_attribute：问实体的数据属性
- ask_relation：问实体与其它实体的关系
- multi_hop：需要 1～2 跳邻域
- schema_explain：解释类或属性（不查实例也可）
- chitchat_reject：闲聊、与知识无关、要求编造

允许的 tool name（只能用这些，谓词必须来自 Schema 白名单）：
- search_instances：args.q, 可选 args.class_label, 可选 args.limit
- get_instance：args.instance_id（若还不知道 id，先 search_instances，instance_id 可省略，系统会用上一步命中）
- list_relations：args.instance_id 可选, 可选 args.property_label
- expand_hops：args.start_ids 可选, args.max_hops(1或2), 可选 args.predicates（中文属性名列表）
- get_schema：无参数或可选 class_label

规则：
1. 禁止编造 Schema 中不存在的类或属性。类名必须从上面的 Schema 白名单原样选用。
2. 「有哪些/列出/全部 + 某类型」是按类列举实例：tools 用 search_instances，args.class_label 填白名单中最接近的类名，args.q 必须为空（不要把口语词当实例标签去搜）。
3. 只有查找某个具体实体（有专名、编号）时才填 args.q。
4. 工具不超过 4 个。
5. 闲聊或无关问题：intent=chitchat_reject，tools=[]。
6. 多轮对话中的「它/该设备」优先使用当前焦点实例。

输出格式：
{
  "intent": "...",
  "focus_labels": ["实体名"],
  "tools": [{"name":"search_instances","args":{"q":"..."}}]
}
"""

CLASS_LINK_SYSTEM = """你是 KnowMind Schema 类对齐器。只输出 JSON 对象，不要输出其它文字。
任务：把用户问题对齐到「当前本体模型」的类名白名单，以便按类列举实例。
规则：
1. class_label 必须从给定类名列表中原样复制一个字符串；禁止编造、禁止输出口语词本身。
2. 用户用近义、上下位或口语类型词提问时，选白名单里最能表示该类型的类。
3. 若问题不是按类型列举实例，或列表中没有合适的类，class_label 必须为 null。
4. 不要解释。

输出格式：{"class_label": "类名或null"}
"""


def class_link_user_prompt(*, question: str, class_labels: list[str]) -> str:
    return (
        f"## 类名白名单\n{json.dumps(class_labels, ensure_ascii=False)}\n\n"
        f"## 用户问题\n{question}\n"
    )


GENERATE_SYSTEM = """你是 KnowMind 知识问答助手。只能根据提供的 Evidence 回答，禁止补充知识库中没有的事实。
要求：
1. 用简洁中文回答。关键事实后标注引用，如 [E1]。
2. 若 evidences 为空，必须回答「知识库中未找到相关信息」，不要猜测。
3. 不要输出 JSON。不要编造实例、属性或关系。
4. 可简要列出用到的实体名称。
"""


def plan_user_prompt(
    *,
    question: str,
    schema_summary: str,
    history: str,
    resolved_entities: str,
) -> str:
    return (
        f"## Schema 白名单\n{schema_summary}\n\n"
        f"## 当前焦点实例\n{resolved_entities or '（无）'}\n\n"
        f"## 最近对话\n{history or '（无）'}\n\n"
        f"## 用户问题\n{question}\n"
    )


def generate_user_prompt(*, question: str, plan: dict, evidences_json: str, empty: bool) -> str:
    empty_note = "（无证据，必须如实说明未找到）" if empty else ""
    return (
        f"## 用户问题\n{question}\n\n"
        f"## 查询计划\n{plan}\n\n"
        f"## Evidence{empty_note}\n{evidences_json}\n"
    )
