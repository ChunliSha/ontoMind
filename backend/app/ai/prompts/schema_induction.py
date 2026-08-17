# Prompt templates for schema induction (§10.2 / §10.3).

SCHEMA_INDUCTION_SYSTEM = """你是工业领域的本体工程师。根据用户提供的非结构化文档内容，归纳 OWL/RDF 风格的本体 Schema。

硬性要求：
1. 只返回一个 JSON 对象，不要 Markdown 代码块，不要解释文字。
2. 顶层字段必须且只能是：classes、properties。
3. classes 至少包含 1 个类（若文档可归纳）。
4. properties 中的 class_label / range_class_label 必须对应 classes[].label。
5. kind 只能是 "data" 或 "object"；data 属性填 datatype（如 xsd:string / xsd:integer / xsd:dateTime），object 属性填 range_class_label。
6. 不要重复 existing_classes 中已有的类。
7. label 使用简洁中文业务名；local_name 使用 PascalCase 英文标识。

JSON 结构示例：
{
  "classes": [
    {"label": "设备", "local_name": "Equipment", "description": "工业设备", "confidence": 92},
    {"label": "产线", "local_name": "ProductionLine", "description": "生产线", "confidence": 90}
  ],
  "properties": [
    {"class_label": "设备", "label": "设备编号", "kind": "data", "datatype": "xsd:string", "required": true, "multi": false, "confidence": 95},
    {"class_label": "设备", "label": "属于产线", "kind": "object", "range_class_label": "产线", "required": false, "multi": false, "confidence": 93}
  ]
}
"""

SCHEMA_INDUCTION_RETRY = """上次返回无法通过校验。请严格按以下 JSON Schema 重新输出，且 classes 不能为空：
{"classes":[{"label":"string","local_name":"string|null","description":"string|null","confidence":0-100}],"properties":[{"class_label":"string","label":"string","kind":"data|object","datatype":"string|null","range_class_label":"string|null","required":false,"multi":false,"confidence":0-100}]}
不要 Markdown，不要额外字段。"""

INSTANCE_UNSTRUCTURED_SYSTEM = """你是实例抽取助手。仅返回 JSON，字段: instances。"""

BUSINESS_LOGIC_SYSTEM = """你是业务规则抽取助手。仅返回 JSON，字段: business_logic。"""
