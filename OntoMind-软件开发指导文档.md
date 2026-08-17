# OntoMind 本体抽取工具 · 软件开发指导文档 (v2)

> 本文档面向执行编码任务的 Agent（如 Claude Code），用于指导其独立完成 OntoMind 项目的前后端全部代码实现。
> 交互与视觉的唯一事实来源（source of truth）是随本文档一同提供的 UCD 原型文件 **`frontendUCD.html`**：所有页面结构、文案、颜色变量、图标（lucide 图标名）、字段名、弹窗表单字段、按钮文案，均以该文件为准。本文档不重复罗列 CSS 数值，而是把原型中的交互行为**翻译为可实现的数据模型、数据库设计、状态机、服务边界、API 契约与工程结构**。
>
> **v2 变更说明**：相较 v1，本版新增「系统业务流程」「状态机设计」「Service/Repository 职责边界」「DTO 契约」「统一错误码」「AI 模块设计」「编码规范」等章节，目的是把 v1 中隐含在 Agent 常识里的架构决策显式化，减少 Agent 自由发挥导致的返工。这些新增内容基于对 v1 的一轮工程评审，评审中部分建议（如引入 Redis 缓存、Celery 队列、Schema 分支锁定发布模型）被判断为超出当前 MVP 范围，改为以"可选/后续演进路径"的形式保留，未强制引入新基础设施，理由见对应章节。

---

## 0. 快速参照表（UI 模块 → 前端路由 → 后端资源）

| UCD 原型中的模块 | 原型 view id | 前端路由建议 | 后端主要资源 |
|---|---|---|---|
| 快速指引首页 | `view-home` | `/` | `GET /dashboard/summary`、`/dashboard/activity` |
| 结构化数据管理 | `view-structured` | `/data/structured` | `/db-sources` |
| 非结构化数据管理 | `view-unstructured` | `/data/unstructured` | `/files` |
| Schema 抽取与设计（工作区/管理） | `view-schema` | `/schema` | `/schemas`、`/schemas/{id}/classes`、`/classes/{id}/properties` |
| 本体抽取（非结构化/结构化） | `view-extract` | `/extraction/instances` | `/extraction/instances/*`、`/mappings` |
| 业务逻辑抽取 | `view-biz-logic` | `/extraction/business-logic` | `/extraction/business-logic`、`/business-logic-rules` |
| 图谱探索 | `view-graph` | `/graph` | `/graph` |

---

## 1. 项目概述

### 1.1 产品定位
OntoMind 是一个本体（Ontology）构建工作台，覆盖四个顺序阶段：业务数据集成 → Schema 抽取与设计 → AI 辅助抽取（本体实例 + 业务逻辑）→ 图谱探索。详细流程见 §2。

### 1.2 名词表（贯穿前后端，命名需保持一致）

| 术语 | 说明 | 对应 OWL/RDF 概念 |
|---|---|---|
| Schema | 一个本体骨架的版本快照，包含若干类与属性 | `owl:Ontology` |
| Class（类） | 概念/实体类型 | `owl:Class` |
| Data Property（数据属性） | 类的字面量属性 | `owl:DatatypeProperty` |
| Object Property（对象属性） | 类到类的关系属性 | `owl:ObjectProperty` |
| Instance（实例） | 某个类的具体个体 | `owl:NamedIndividual` |
| Field Mapping（字段映射） | 结构化表字段 → Schema 属性的绑定规则 | 无直接 OWL 对应，属于 ETL 元数据 |
| Business Logic Rule（业务逻辑规则） | 从文档中抽取的因果/约束规则 | 不建模为 RDF，独立 JSON 存储 |
| Extraction Task（抽取任务） | 一次异步抽取作业（Schema归纳/实例抽取/业务逻辑抽取） | — |

### 1.3 技术栈（已确定，Agent 不应更换）

| 层 | 技术 |
|---|---|
| 前端 | Angular 20+（Standalone Components + Signals，无 NgModule） |
| 后端 | Python 3.11+ / FastAPI（async）、Pydantic v2 |
| 数据库 | PostgreSQL 15+ |
| ORM / 迁移 | SQLAlchemy 2.0（async）+ Alembic |
| RDF/OWL 处理 | `rdflib`（TTL 序列化与解析），不引入 Jena/Fuseki |
| 鉴权 | **暂不实现**。所有接口公开访问；数据模型预留 `created_by` / `published_by` 等可空字段，便于未来接入鉴权而不需迁移重建 |
| 文件存储 | 抽象 `StorageBackend` 接口，提供 `LocalStorageBackend` 与 `MinIOStorageBackend` 两个实现 |
| AI/LLM | 抽象 `LLMProvider` 接口，先实现 `MockLLMProvider`（返回结构化模拟数据）保证联调不被真实模型接入阻塞，详见 §10 |
| 异步任务 | MVP 阶段使用 FastAPI 进程内 `asyncio` 任务 + 数据库任务表做状态持久化与轮询；**不引入 Celery/Redis**——当前任务量级（单工作区、演示/试点场景）不需要分布式队列，引入会增加部署与调试复杂度而收益有限。若后续任务并发量显著增长，可平滑替换为 Celery/arq + Redis，`extraction_task` 表结构无需变更，这是刻意设计的可演进点 |
| 图谱缓存 | **可选**，用纯 Postgres 的 `graph_cache` 表做失效式缓存（§9.4），不引入 Redis，理由同上 |

---

## 2. 系统业务流程（Pipeline）

这是最容易被 Agent 忽略、但决定"谁依赖谁"的一章。**在实现任何一个 API 之前，必须先理解下面这张全局流程图**，否则容易做出「结构化实例抽取依赖 Mapping」「图谱探索在没有数据时应报错而不是返回空图」这类隐性依赖判断错误。

### 2.1 端到端主流程

```mermaid
flowchart TD
    subgraph 非结构化路径
    A1[上传文档 POST /files] --> A2[异步解析纯文本 status: parsing→ready]
    A2 --> A3[转标准MD]
    A3 --> A4[转本体MD]
    end

    subgraph 结构化路径
    B1[新增数据库连接 POST /db-sources] --> B2[测试连接]
    B2 --> B3[浏览表 GET /tables]
    B3 --> B4[勾选建模用表]
    end

    A4 --> C{Schema 是否已存在?}
    C -- 否，从零开始 --> D[AI Schema归纳 schema_induction]
    C -- 是，直接设计 --> E
    D --> E[人工审视/修改 类与属性]
    E --> F[发布 Schema POST /schemas/id/publish]

    F --> G1[非结构化实例抽取]
    A4 -.供文本输入.-> G1
    F --> G2[配置字段映射 POST /mappings]
    B4 -.供表结构输入.-> G2
    G2 --> G3[结构化实例抽取 ETL]

    G1 --> H[(实例入库 ontology_instance)]
    G3 --> H

    H --> I[业务逻辑抽取]
    A4 -.供业务文档输入.-> I
    H --> J[图谱探索可视化 GET /graph]
    I --> J

    F -.任意阶段可导出.-> K[导出 TTL]
    I --> L[导出业务逻辑 JSON]
```

### 2.2 显式依赖规则（Agent 实现校验逻辑时必须遵守）

| 动作 | 前置依赖 | 缺失时的正确行为 |
|---|---|---|
| Schema 归纳 (`/schemas/{id}/induce`) | 至少 1 个 `status=ready` 的非结构化文件 | 400 + `FILE_004`「请先选择至少一个已解析完成的文档」 |
| 非结构化实例抽取 | Schema 下**至少 1 个 class**；至少 1 个 `status=ready` 文件 | 400 + `SCHEMA_005`「目标 Schema 尚无任何类，请先完成 Schema 设计」 |
| 结构化实例抽取 | 对应 class 已存在 `field_mapping` 且已保存至少 1 个 binding | 400 + `MAPPING_001` |
| 业务逻辑抽取 | Schema 下**至少 1 条 instance**（用作实体锚点）；至少 1 个业务文档 | 400 + `BIZLOGIC_001`「请先完成本体实例抽取，再进行业务逻辑抽取」 |
| 图谱探索 `mode=schema` | 无强制依赖 | Schema 为空时返回 `{nodes: [], links: []}`，前端展示空状态，**不报错** |
| 图谱探索 `mode=instance` | 无强制依赖 | 同上，返回空数组而非 404 |
| TTL 导出 | 无强制依赖 | Schema 为空时仍可导出，只含 `om: a owl:Ontology .` 声明 |

### 2.3 关键异步流程时序图

其余异步任务（结构化实例抽取、业务逻辑抽取、Schema 归纳）均遵循与下图相同的时序模式（Router 快速返回 `task_id` → 后台协程执行 → 前端轮询），不再逐一画图，Agent 应按此模式类推实现。

**文件上传与解析：**

```mermaid
sequenceDiagram
    participant FE as Angular
    participant API as FastAPI Router
    participant SVC as FileService
    participant ST as StorageBackend
    participant DB as PostgreSQL

    FE->>API: POST /files (multipart)
    API->>SVC: save_file(...)
    SVC->>ST: save(key, bytes)
    ST-->>SVC: storage_path
    SVC->>DB: INSERT data_source_file(status=pending)
    SVC-->>API: FileRead
    API-->>FE: 201 {id, status: pending}
    Note over SVC: asyncio.create_task 触发后台解析
    SVC->>DB: UPDATE status=parsing
    SVC->>SVC: parse_text()
    SVC->>DB: UPDATE status=ready, extracted_text=...
    FE->>API: GET /files/{id}（下次刷新或轮询）
    API-->>FE: status: ready
```

**非结构化实例抽取（其余抽取任务类推）：**

```mermaid
sequenceDiagram
    participant FE as Angular
    participant API as FastAPI Router
    participant SVC as ExtractionService
    participant AI as LLMProvider
    participant DB as PostgreSQL

    FE->>API: POST /extraction/instances/unstructured {schema_id, file_ids}
    API->>SVC: run_unstructured(...)
    SVC->>DB: INSERT extraction_task(status=pending)
    SVC-->>API: task_id
    API-->>FE: 202 {task_id}
    Note over SVC: asyncio 后台协程启动
    SVC->>DB: UPDATE task status=running
    loop 每个文件
        SVC->>AI: extract_instances(text, schema_snapshot)
        AI-->>SVC: AIResult[InstanceExtractionResult]
        SVC->>DB: INSERT instance / data_value / relation
        SVC->>DB: UPDATE task progress
    end
    SVC->>DB: UPDATE task status=succeeded, output_summary
    loop 前端每 300~500ms 轮询
        FE->>API: GET /extraction/tasks/{id}
        API-->>FE: {status, progress}
    end
```

---

## 3. 总体架构

```
┌─────────────────────────┐        HTTPS/JSON        ┌──────────────────────────────┐
│  Angular 20+ SPA         │ ────────────────────────▶│  FastAPI (uvicorn/gunicorn)   │
│  (standalone + signals)  │◀──────────────────────── │  router → service → repository │
└─────────────────────────┘                            │  ai/ · rdf/ · storage/          │
                                                         └───────────────┬────────────────┘
                                                                         │ SQLAlchemy async
                                                                         ▼
                                                            ┌─────────────────────┐
                                                            │  PostgreSQL          │
                                                            └─────────────────────┘
```

设计原则：
- **关系表为唯一真源（source of truth）**。TTL 文件不是持久化存储的主数据，而是从关系表**按需生成**的导出产物；导入 TTL 时用 `rdflib` 解析后写回关系表。
- **实例不是三元组大表，而是三张结构化表**（`ontology_instance` / `instance_data_value` / `instance_relation`），导出 TTL 时再拼装成三元组。
- **图谱接口直接返回前端所需的 `{nodes, links}` 结构**，不做通用 SPARQL 查询封装。
- **分层严格单向依赖**：`router → service → repository → ORM model`，任何一层不得跳级调用（详见 §7.2）。

---

## 4. 领域模型与 ER 图

```mermaid
erDiagram
    DATA_SOURCE_DB ||--o{ DATA_SOURCE_TABLE : has
    DATA_SOURCE_TABLE ||--o{ DATA_SOURCE_TABLE_COLUMN : has
    DATA_SOURCE_FILE {
        uuid id
        string status
    }

    ONTOLOGY_SCHEMA ||--o{ ONTOLOGY_CLASS : has
    ONTOLOGY_CLASS ||--o{ ONTOLOGY_PROPERTY : "domain of"
    ONTOLOGY_CLASS ||--o{ ONTOLOGY_CLASS : "parent of (self)"
    ONTOLOGY_PROPERTY }o--o| ONTOLOGY_CLASS : "range (object property only)"

    ONTOLOGY_SCHEMA ||--o{ FIELD_MAPPING : has
    ONTOLOGY_CLASS ||--o{ FIELD_MAPPING : "mapped by"
    DATA_SOURCE_TABLE ||--o{ FIELD_MAPPING : "source of"
    FIELD_MAPPING ||--o{ FIELD_MAPPING_BINDING : has
    ONTOLOGY_PROPERTY ||--o{ FIELD_MAPPING_BINDING : "bound to"

    ONTOLOGY_SCHEMA ||--o{ EXTRACTION_TASK : has

    ONTOLOGY_SCHEMA ||--o{ ONTOLOGY_INSTANCE : has
    ONTOLOGY_CLASS ||--o{ ONTOLOGY_INSTANCE : "instance of"
    ONTOLOGY_INSTANCE ||--o{ INSTANCE_DATA_VALUE : has
    ONTOLOGY_PROPERTY ||--o{ INSTANCE_DATA_VALUE : "value of"
    ONTOLOGY_INSTANCE ||--o{ INSTANCE_RELATION : "subject of"
    ONTOLOGY_INSTANCE ||--o{ INSTANCE_RELATION : "object of"
    ONTOLOGY_PROPERTY ||--o{ INSTANCE_RELATION : "relation type"

    ONTOLOGY_SCHEMA ||--o{ BUSINESS_LOGIC_RULE : has
    DATA_SOURCE_FILE ||--o{ BUSINESS_LOGIC_RULE : "source of"
    EXTRACTION_TASK ||--o{ BUSINESS_LOGIC_RULE : produces
    EXTRACTION_TASK ||--o{ ONTOLOGY_INSTANCE : produces
```

---

## 5. 状态机设计

> Agent 修改任意实体状态字段前，必须确认该状态转换在下列状态机中存在对应的边；不存在的转换应在 Service 层拒绝并抛出对应错误码，而不是静默允许。

### 5.1 ExtractionTask 状态机

```mermaid
stateDiagram-v2
    [*] --> pending: 创建任务，Router 立即返回 task_id
    pending --> running: 后台协程开始执行
    running --> succeeded: 全部数据处理完成
    running --> failed: 抛出异常 / LLM 调用失败 / 校验失败
    succeeded --> [*]
    failed --> [*]
```

**重要澄清**：原型中"重新抽取"按钮在本设计中实现为**创建一条新的 `extraction_task` 记录**，而不是把失败的任务行原地从 `failed` 拨回 `running`。失败任务保留作为审计记录。Agent 不应实现 `failed → running` 的原地状态回退。

### 5.2 DataSourceFile 状态机

```mermaid
stateDiagram-v2
    [*] --> pending: 上传成功
    pending --> parsing: 后台开始解析
    parsing --> ready: 文本提取成功
    parsing --> failed: 解析异常
    failed --> parsing: 用户重新触发解析（预留接口位，非本期必须）
    ready --> ready: 转标准MD/转本体MD 只填充 standard_md_path/ontology_md_path，不改变主状态
```

### 5.3 DataSourceDB 连接状态机

```mermaid
stateDiagram-v2
    [*] --> pending: 创建连接（尚未测试）
    pending --> connected: 测试连接成功
    pending --> failed: 测试连接失败
    connected --> syncing: 触发"查看表" reflect
    syncing --> connected: reflect 完成
    failed --> pending: 用户编辑连接信息后重新测试
```

### 5.4 OntologySchema 状态机

```mermaid
stateDiagram-v2
    [*] --> draft: 创建
    draft --> draft: 增删改类/属性（version 不变）
    draft --> published: POST /publish（version += 1，写 change_log）
    published --> published: 继续编辑类/属性（不锁定，简化设计见下）
    published --> published: 再次 publish（version 再 +1）
```

**简化设计说明**：`published` 状态**不锁定编辑**——用户仍可在工作区继续修改已发布的 Schema，每次 `publish` 只是打一个版本快照（`version` 自增 + `change_log` 记录本次说明），不实现"发布后只读、需新建草稿分支才能改"的强流程。这是当前阶段的刻意简化：完整的分支/锁定/Diff 机制属于独立的版本控制子系统，超出本期范围，如未来需要，应新增 `schema_version` 快照表而不是改造现有状态机。

---

## 6. 数据库设计（PostgreSQL DDL）

> 命名规范：表名/字段名 `snake_case`；主键统一 `id UUID DEFAULT gen_random_uuid()`（需启用 `pgcrypto` 扩展）；所有表含 `created_at TIMESTAMPTZ DEFAULT now()`，可变更表另加 `updated_at`。枚举优先使用 `VARCHAR` + `CHECK` 约束，便于后续用 Alembic 平滑修改取值范围。所有表额外预留 `created_by UUID`（可空，本期恒为 NULL，为未来鉴权预留，DDL 中不重复列出，Agent 落地时统一追加）。

### 6.1 业务数据集成

```sql
CREATE TABLE data_source_db (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            VARCHAR(128) NOT NULL,
  db_type         VARCHAR(16) NOT NULL CHECK (db_type IN ('postgres','mysql','gaussdb')),
  host            VARCHAR(255) NOT NULL,
  port            INTEGER NOT NULL,
  database_name   VARCHAR(128) NOT NULL,
  username        VARCHAR(128) NOT NULL,
  password_enc    TEXT NOT NULL,               -- Fernet 对称加密存储，见 §7.6
  status          VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','connected','failed','syncing')),
  last_error      TEXT,
  table_count     INTEGER DEFAULT 0,
  last_synced_at  TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE data_source_table (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  data_source_id  UUID NOT NULL REFERENCES data_source_db(id) ON DELETE CASCADE,
  table_schema    VARCHAR(128) NOT NULL DEFAULT 'public',
  table_name      VARCHAR(128) NOT NULL,
  row_count       BIGINT,
  column_count    INTEGER,
  selected_for_modeling BOOLEAN NOT NULL DEFAULT false,
  is_generated    BOOLEAN NOT NULL DEFAULT false,  -- 由"构建表SQL"自动创建
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(data_source_id, table_schema, table_name)
);

CREATE TABLE data_source_table_column (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  table_id        UUID NOT NULL REFERENCES data_source_table(id) ON DELETE CASCADE,
  column_name     VARCHAR(128) NOT NULL,
  data_type       VARCHAR(64) NOT NULL,
  is_primary_key  BOOLEAN NOT NULL DEFAULT false,
  ordinal         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE data_source_file (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            VARCHAR(255) NOT NULL,
  file_type       VARCHAR(16) NOT NULL,
  storage_backend VARCHAR(16) NOT NULL CHECK (storage_backend IN ('local','minio')),
  storage_path    TEXT NOT NULL,
  size_bytes      BIGINT NOT NULL DEFAULT 0,
  status          VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','parsing','ready','failed')),
  error_message   TEXT,
  standard_md_path  TEXT,
  ontology_md_path  TEXT,
  extracted_text  TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 6.2 Schema（类 / 属性，含版本控制字段）

```sql
CREATE TABLE ontology_schema (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name         VARCHAR(128) NOT NULL,
  base_iri     VARCHAR(255) NOT NULL DEFAULT 'http://example.com/ontomind/schema#',
  status       VARCHAR(16) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
  version      INTEGER NOT NULL DEFAULT 1,
  change_log   TEXT,                 -- 每次 publish 时用户填写的版本说明，对应原型"版本说明"输入框
  published_at TIMESTAMPTZ,
  published_by UUID,                 -- 预留，当前恒为 NULL
  source       VARCHAR(16) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','ai_induced','imported_ttl')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ontology_class (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  schema_id        UUID NOT NULL REFERENCES ontology_schema(id) ON DELETE CASCADE,
  label            VARCHAR(128) NOT NULL,
  local_name       VARCHAR(128),
  parent_class_id  UUID REFERENCES ontology_class(id) ON DELETE SET NULL,
  description      TEXT,
  source           VARCHAR(16) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','ai')),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(schema_id, label)
);

CREATE TABLE ontology_property (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  schema_id      UUID NOT NULL REFERENCES ontology_schema(id) ON DELETE CASCADE,
  domain_class_id UUID NOT NULL REFERENCES ontology_class(id) ON DELETE CASCADE,
  label          VARCHAR(128) NOT NULL,
  local_name     VARCHAR(128),
  kind           VARCHAR(8) NOT NULL CHECK (kind IN ('data','object')),
  datatype       VARCHAR(32),        -- kind=data 时必填：xsd:string/xsd:int/xsd:dateTime/xsd:decimal/xsd:boolean/xsd:json
  range_class_id UUID REFERENCES ontology_class(id), -- kind=object 时必填
  required       BOOLEAN NOT NULL DEFAULT false,
  multi          BOOLEAN NOT NULL DEFAULT false,
  source         VARCHAR(16) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','ai')),
  confidence     NUMERIC(5,2),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(domain_class_id, label)
);
```

### 6.3 结构化字段映射

```sql
CREATE TABLE field_mapping (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  schema_id     UUID NOT NULL REFERENCES ontology_schema(id) ON DELETE CASCADE,
  class_id      UUID NOT NULL REFERENCES ontology_class(id) ON DELETE CASCADE,
  table_id      UUID NOT NULL REFERENCES data_source_table(id) ON DELETE CASCADE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(class_id, table_id)
);

CREATE TABLE field_mapping_binding (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mapping_id      UUID NOT NULL REFERENCES field_mapping(id) ON DELETE CASCADE,
  target_kind     VARCHAR(16) NOT NULL CHECK (target_kind IN ('instance_uri','property')),
  target_property_id UUID REFERENCES ontology_property(id) ON DELETE CASCADE,
  source_column   VARCHAR(128) NOT NULL
);
```

### 6.4 抽取任务

```sql
CREATE TABLE extraction_task (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_type      VARCHAR(24) NOT NULL CHECK (task_type IN
                   ('schema_induction','instance_unstructured','instance_structured','business_logic')),
  status         VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','succeeded','failed')),
  schema_id      UUID REFERENCES ontology_schema(id) ON DELETE SET NULL,
  input          JSONB NOT NULL DEFAULT '{}',
  progress       NUMERIC(5,2) NOT NULL DEFAULT 0,
  output_summary JSONB,
  error_message  TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at     TIMESTAMPTZ,
  finished_at    TIMESTAMPTZ
);
```

### 6.5 本体实例

```sql
CREATE TABLE ontology_instance (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  schema_id      UUID NOT NULL REFERENCES ontology_schema(id) ON DELETE CASCADE,
  class_id       UUID NOT NULL REFERENCES ontology_class(id) ON DELETE CASCADE,
  label          VARCHAR(255) NOT NULL,
  local_name     VARCHAR(255),
  source_type    VARCHAR(16) NOT NULL CHECK (source_type IN ('ai_unstructured','structured_mapping','manual')),
  source_ref     JSONB,
  confidence     NUMERIC(5,2),
  extraction_task_id UUID REFERENCES extraction_task(id) ON DELETE SET NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_instance_class ON ontology_instance(class_id);

CREATE TABLE instance_data_value (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  instance_id   UUID NOT NULL REFERENCES ontology_instance(id) ON DELETE CASCADE,
  property_id   UUID NOT NULL REFERENCES ontology_property(id) ON DELETE CASCADE,
  value         TEXT NOT NULL
);
CREATE INDEX idx_data_value_instance ON instance_data_value(instance_id);

CREATE TABLE instance_relation (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_instance_id UUID NOT NULL REFERENCES ontology_instance(id) ON DELETE CASCADE,
  property_id       UUID NOT NULL REFERENCES ontology_property(id) ON DELETE CASCADE,
  object_instance_id UUID NOT NULL REFERENCES ontology_instance(id) ON DELETE CASCADE
);
CREATE INDEX idx_relation_subject ON instance_relation(subject_instance_id);
```

### 6.6 业务逻辑规则

```sql
CREATE TABLE business_logic_rule (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  schema_id       UUID NOT NULL REFERENCES ontology_schema(id) ON DELETE CASCADE,
  rule_type       VARCHAR(16) NOT NULL CHECK (rule_type IN ('causality','constraint')),
  description     TEXT NOT NULL,
  condition       JSONB NOT NULL,
  consequence     JSONB,
  action_required TEXT,
  severity        VARCHAR(16),
  source_doc_id   UUID REFERENCES data_source_file(id),
  extraction_task_id UUID REFERENCES extraction_task(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 6.7 图谱缓存（可选，非 MVP 必需）

```sql
-- 图谱数据量增大、组装耗时明显后再启用；纯 Postgres 方案，不引入 Redis
CREATE TABLE graph_cache (
  schema_id   UUID NOT NULL REFERENCES ontology_schema(id) ON DELETE CASCADE,
  mode        VARCHAR(16) NOT NULL,
  payload     JSONB NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (schema_id, mode)
);
```
失效策略：任何 `ontology_class` / `ontology_property` / `ontology_instance` / `instance_relation` 的写操作提交后，删除该 `schema_id` 在 `graph_cache` 中的全部行（简单粗暴但正确）；下次 `GET /graph` 未命中缓存时重新组装并写入。

---

## 7. 后端架构（FastAPI）

### 7.1 目录结构

```
backend/
  app/
    main.py
    core/
      config.py
      security.py                 # Fernet 加密工具
      exceptions.py                # ErrorCode 枚举 + 自定义异常类 + 全局异常处理器
    db/
      session.py
      base.py
    models/                        # SQLAlchemy ORM
      data_source.py
      schema.py
      mapping.py
      extraction.py
      instance.py
      business_logic.py
    repositories/                  # ★ 纯数据库 CRUD，见 §7.2
      db_source_repository.py
      table_repository.py
      file_repository.py
      schema_repository.py
      class_repository.py
      property_repository.py
      mapping_repository.py
      task_repository.py
      instance_repository.py
      instance_relation_repository.py
      business_logic_repository.py
    schemas/                       # Pydantic DTO，见 §7.3
      data_source.py
      schema.py
      mapping.py
      extraction.py
      instance.py
      business_logic.py
      graph.py
      dashboard.py
      common.py                    # PageResponse、ErrorResponse 等通用 DTO
    api/
      v1/
        router.py
        routers/
          db_sources.py
          files.py
          schemas.py
          mappings.py
          instances.py
          business_logic.py
          graph.py
          dashboard.py
    services/                      # 业务编排，见 §7.2
      db_source_service.py
      file_service.py
      schema_service.py
      mapping_service.py
      extraction_service.py
      graph_service.py
      business_logic_service.py
      dashboard_service.py
    ai/
      base.py                      # LLMProvider 抽象基类 + AIResult 统一信封
      mock_provider.py
      openai_compatible_provider.py
      prompts/
        schema_induction.py
        instance_unstructured.py
        business_logic.py
    rdf/
      ttl_builder.py
      ttl_parser.py
    storage/
      base.py
      local_backend.py
      minio_backend.py
    tasks/
      runner.py
  alembic/versions/
  tests/{unit,integration}/
  pyproject.toml
  .env.example
```

### 7.2 分层职责边界（★ 新增，Agent 必须严格遵守）

**总原则**：`Router → Service → Repository → ORM`，单向依赖，禁止跳级或反向调用。

#### Router 层
- 只做：请求解析、依赖注入 `AsyncSession`、调用 Service、把 Service 返回的 DTO 直接作为响应体返回。
- 禁止：出现任何 `session.execute(...)` / ORM 查询语句；禁止在 Router 里写业务判断（如"名称重复"）。

#### Service 层职责表

| Service | 职责 | 禁止事项 | 主要依赖 |
|---|---|---|---|
| `DbSourceService` | 连接 CRUD、测试连接、`sqlalchemy.inspect` 反射表结构写入 `DataSourceTable/Column` | 不做 AI 调用、不做 ETL | `DbSourceRepository`, `TableRepository` |
| `FileService` | 文件 CRUD、上传落地、异步解析文本、转标准/本体 MD、构建表 SQL 生成与 `materialize-table` | 不承担"实例抽取"业务（那是 `ExtractionService` 的职责，即使输入都是文件文本） | `FileRepository`, `StorageBackend`, 可选调用 `LLMProvider`（仅限"转本体MD"的结构化标注） |
| `SchemaService` | Schema/Class/Property **手动** CRUD、`publish`、调用 `RDFService` 做 TTL 导入导出 | 不发起异步抽取任务（Schema 归纳属于 `ExtractionService`）、不组装图谱 JSON | `SchemaRepository`, `ClassRepository`, `PropertyRepository`, `rdf/` |
| `MappingService` | 字段映射 CRUD、返回候选源字段/目标属性列表 | 不执行 ETL 本身（只管理配置）、不调用 LLM | `MappingRepository`, `TableRepository`, `PropertyRepository` |
| `ExtractionService` | **编排全部四类异步任务**：创建/更新 `extraction_task`、调用 `LLMProvider`（schema_induction / instance_unstructured / business_logic）、执行确定性 ETL（instance_structured）、把结果写入对应 Repository | 不做手动 CRUD 入口（那是各自 Service 的职责）、不做前端展示逻辑 | `TaskRepository`, `SchemaRepository`/`ClassRepository`/`PropertyRepository`（写归纳结果）, `InstanceRepository`, `MappingRepository`（读取执行 ETL）, `BusinessLogicRepository`, `LLMProvider` |
| `GraphService` | 只读查询 Schema+Instance，组装 `{nodes, links}`，节点详情查询，管理 `graph_cache` 读写 | 不做任何业务写操作 | `ClassRepository`, `PropertyRepository`, `InstanceRepository`, `InstanceRelationRepository` |
| `BusinessLogicService` | 已持久化规则的查询与导出 | 不发起抽取任务（抽取由 `ExtractionService` 完成后写入，本 Service 只读） | `BusinessLogicRepository` |
| `DashboardService` | 聚合统计、最近动态查询 | 不做写操作 | 多个只读 Repository |
| `RDFService`（内部工具，不暴露路由） | `ttl_builder`/`ttl_parser`，TTL 导入的事务边界控制（见 §9.2） | 不直接被 Router 调用，只被 `SchemaService` 调用 | `rdflib` |

#### Repository 层规范（★ 新增）
- 每个聚合根一个 Repository 类，方法只包含 `get_by_id` / `list` / `create` / `update` / `delete` 及必要的聚合查询（如 `count_by_class`）。
- 方法签名只接受/返回 **ORM 模型对象**或简单 dataclass，**不做**面向 API 的序列化（那是 Service 把 ORM 转成 §7.3 DTO 的职责）。
- 禁止 `import app.ai`、`import app.storage`、`import app.rdf` —— Repository 只能 `import app.models` 和 SQLAlchemy。
- 禁止包含业务规则判断（如"属性名是否重复"应在 Service 层查询后判断，或直接依赖数据库 `UNIQUE` 约束抛错、由 Service 捕获转换为 §7.4 的错误码）。
- 禁止循环内逐条执行 SQL（N+1）；批量写用 `session.execute(insert(Model), list_of_dicts)`，批量读用 `selectinload`/`joinedload` 预加载关联。

### 7.3 DTO 契约（★ 新增，节选关键模型，其余按同一模式补全）

> 命名约定：`XxxCreate`（创建请求）、`XxxUpdate`（更新请求，字段全 `Optional`）、`XxxRead`（响应，`model_config = ConfigDict(from_attributes=True)`）。所有 `Read` 模型的 `id` 序列化为字符串（UUID 转 str）。

```python
# schemas/common.py
class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

class ErrorDetail(BaseModel):
    code: str            # 见 §7.4 错误码表
    message: str
    field: str | None = None   # 表单字段级错误时填写，供前端定位具体输入框

class ErrorResponse(BaseModel):
    error: ErrorDetail
```

```python
# schemas/schema.py
class ClassCreate(BaseModel):
    label: str
    local_name: str | None = None
    parent_class_id: str | None = None
    description: str | None = None

class PropertyCreate(BaseModel):
    label: str
    kind: Literal['data', 'object']
    datatype: str | None = None          # kind=data 时必填
    range_class_id: str | None = None    # kind=object 时必填
    required: bool = False
    multi: bool = False

class PropertyRead(BaseModel):
    id: str
    label: str
    kind: Literal['data', 'object']
    datatype: str | None
    range_class_label: str | None        # 展示用，Service 层从 range_class_id 解析出 label
    required: bool
    multi: bool
    source: Literal['manual', 'ai']
    confidence: float | None

class SchemaRead(BaseModel):
    id: str
    name: str
    status: Literal['draft', 'published']
    version: int
    class_count: int
    property_count: int
    updated_at: datetime

class SchemaPublishRequest(BaseModel):
    change_log: str | None = None
```

```python
# schemas/extraction.py
class ExtractionTaskRead(BaseModel):
    id: str
    task_type: Literal['schema_induction','instance_unstructured','instance_structured','business_logic']
    status: Literal['pending','running','succeeded','failed']
    progress: float
    output_summary: dict | None
    error_message: str | None

class UnstructuredExtractionRequest(BaseModel):
    schema_id: str
    file_ids: list[str]
    ai_config: dict | None = None   # 预留：temperature/top_p/confidence_threshold 等

class StructuredExtractionRequest(BaseModel):
    schema_id: str
    mapping_ids: list[str]
```

```python
# schemas/graph.py
class GraphNode(BaseModel):
    id: str
    type: Literal['class','obj_prop','data_prop','instance']
    label: str
    dp: int | None = None       # 仅 type=class
    op: int | None = None
    inst: int | None = None
    classId: str | None = None  # 仅 type=instance

class GraphLink(BaseModel):
    source: str
    target: str
    type: Literal['schema_link','instance_of','instance_rel']
    label: str | None = None

class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]
```

其余模块（`DbSourceCreate/Read`、`FileRead`、`MappingCreate`、`InstanceRead`、`BusinessLogicRuleRead`、`DashboardSummary`）按同一命名约定与 §6 DDL 字段对齐补全，字段可见性规则：**凡是 DDL 中标注为内部实现细节的字段（如 `password_enc`）永不出现在任何 `Read` DTO 中**。

### 7.4 统一响应与错误码规范（★ 增强）

成功响应：列表接口统一 `PageResponse[T]`；单资源接口直接返回对应 `XxxRead`；异步任务创建接口返回 `202 {task_id, status: "pending"}`。

失败响应统一 `ErrorResponse`（结构见 §7.3），HTTP 状态码语义：`400` 校验失败、`404` 资源不存在、`409` 状态冲突（如重复触发同一进行中任务）、`500` 未预期异常（仍需带 `code: "INTERNAL_ERROR"`，禁止裸 `HTTPException(500, "error")`）。

**错误码表**（前缀对应模块，三位数字；`message` 文案应尽量复用原型中 `*-error` 元素的中文提示，保证前后端一致）：

| Code | 触发场景 | message 示例 |
|---|---|---|
| `DB_SOURCE_001` | 连接测试失败 | 连接失败，请检查主机地址与端口 |
| `DB_SOURCE_002` | 连接名称已存在 | 该连接名称已存在，请更换 |
| `FILE_001` | 文件类型不支持 | 暂不支持该文件类型 |
| `FILE_002` | 文件大小超限 | 单个文件不能超过 200MB |
| `FILE_003` | 文件解析失败 | 文件解析失败，请检查文件是否损坏 |
| `FILE_004` | 无可用于抽取的已就绪文件 | 请先选择至少一个已解析完成的文档 |
| `SCHEMA_001` | 类名称已存在 | 该类已存在，请更换名称 |
| `SCHEMA_002` | 属性名称在该类下已存在 | 该域下已存在同名属性，请更换名称 |
| `SCHEMA_003` | TTL 解析失败 | TTL 文件解析失败，请检查语法（第 N 行） |
| `SCHEMA_004` | 删除存在实例引用的类 | 该类下存在实例数据，请先清理实例后再删除 |
| `SCHEMA_005` | Schema 下无任何类 | 目标 Schema 尚无任何类，请先完成 Schema 设计 |
| `MAPPING_001` | 未配置实例 URI 绑定 | 请至少绑定一个字段作为实例 URI |
| `MAPPING_002` | 源字段类型与目标属性数据类型不兼容 | 字段类型与属性数据类型不匹配 |
| `TASK_001` | 任务不存在 | 抽取任务不存在 |
| `TASK_002` | 任务已在运行中 | 该任务正在执行，请勿重复触发 |
| `GRAPH_001` | Schema 不存在 | 指定的 Schema 不存在 |
| `BIZLOGIC_001` | 缺少参照的本体实例数据 | 请先完成本体实例抽取，再进行业务逻辑抽取 |
| `INTERNAL_ERROR` | 未分类异常 | 服务器内部错误，请稍后重试 |

**与前端表单校验的对应关系**：`ErrorDetail.field` 字段（如 `"label"`）应与 Angular Reactive Form 的 `controlName` 保持一致，前端拦截器捕获到 `error.field` 后直接调用 `form.get(field)?.setErrors(...)`，从而复现原型中 `schemaClassLabel.setAttribute('data-invalid','true')` 的红框高亮效果——这样后端一次改动即可自动驱动前端定位到具体输入框，无需前后端分别维护校验规则。

### 7.5 异步任务机制
参见 §2.3 时序图。核心实现：`asyncio.create_task(runner.run(task_id))`，`runner` 内更新 `extraction_task.status/progress`，前端轮询 `GET /extraction/tasks/{id}`。**限制**：仅在单进程部署下保证任务不丢失；多副本水平扩展时需替换为 Celery/arq + Redis（表结构不变）。

### 7.6 密码加密与文件存储抽象
- `data_source_db.password_enc` 用 `cryptography.fernet.Fernet` 加密，密钥来自环境变量 `DB_SECRET_KEY`，任何 `Read` DTO 中不得出现该字段。
- `StorageBackend` 抽象：
  ```python
  class StorageBackend(Protocol):
      async def save(self, key: str, content: bytes, content_type: str) -> str: ...
      async def read(self, key: str) -> bytes: ...
      async def delete(self, key: str) -> None: ...
      async def url(self, key: str) -> str: ...
  ```
  `data_source_file.storage_backend` 决定运行时选用哪个实现。

---

## 8. API 接口规范

> 统一前缀 `/api/v1`。以下表格中「原型触发点」列出 `frontendUCD.html` 中对应的按钮/元素 id。

### 8.1 结构化数据管理

| Method | Path | 说明 | 原型触发点 |
|---|---|---|---|
| GET | `/db-sources` | 列表，`?search=&db_type=&status=&page=&page_size=` | 表格 + 搜索/筛选 |
| POST | `/db-sources` | 新增连接（创建后异步测试连接并 reflect 表数量） | `#btn-add-db` → `#db-confirm` |
| POST | `/db-sources/{id}/test-connection` | 单独测试连接 | 表单内"测试连接" |
| GET | `/db-sources/{id}/tables` | reflect 并返回表清单 | 行内"查看表" |
| PATCH | `/db-sources/{id}/tables/selection` | 批量更新 `selected_for_modeling` | 表列表弹窗"确定选择" |
| PATCH | `/db-sources/{id}` | 编辑连接 | 行内"编辑" |
| DELETE | `/db-sources/{id}` | 删除连接 | 行内"删除" |

### 8.2 非结构化数据管理

| Method | Path | 说明 | 原型触发点 |
|---|---|---|---|
| GET | `/files` | 列表，`?search=&file_type=&status=&storage_backend=` | 表格 + 工具栏 |
| POST | `/files` | multipart 上传，异步解析文本 | 拖拽区/"选择文件" |
| GET | `/files/{id}` | 详情 | — |
| GET | `/files/{id}/preview` | 抽取文本片段预览 | 行内"预览" |
| GET | `/files/{id}/download` | 文件流下载 | 行内"下载" |
| PATCH | `/files/{id}` | 重命名 / 编辑正文 | "重命名""编辑" |
| POST | `/files/{id}/convert-standard-md` | 生成标准 MD | "转标准 MD" |
| POST | `/files/{id}/convert-ontology-md` | 生成本体 MD | "转本体 MD" |
| POST | `/files/{id}/build-table-sql` | 识别表格，返回建表 DDL 预览（不落库） | "构建表 SQL"弹窗打开 |
| POST | `/files/{id}/materialize-table` | 执行 DDL 建表并写入 `data_source_table` | "创建表"按钮 |
| DELETE | `/files/{id}` | 删除文件 | "删除" |

### 8.3 Schema 抽取与设计

| Method | Path | 说明 | 原型触发点 |
|---|---|---|---|
| GET | `/schemas` | 列表，`?search=` | Schema 管理 tab 表格 |
| POST | `/schemas` | 新建空 Schema | `#btn-schema-new` |
| GET | `/schemas/{id}` | 详情 | `#schema-select` |
| PATCH | `/schemas/{id}` | 重命名等 | — |
| POST | `/schemas/{id}/publish` | body `SchemaPublishRequest`，见 §5.4 状态机 | `#btn-save-schema` |
| DELETE | `/schemas/{id}` | 删除 | — |
| GET | `/schemas/{id}/classes` | 类列表（含属性数 `cnt`） | 左侧类目 chip 列表 |
| POST | `/schemas/{id}/classes` | 新增类 | `#schema-class-modal` → `#schema-class-confirm` |
| PATCH | `/classes/{class_id}` | 编辑类 | — |
| DELETE | `/classes/{class_id}` | 删除类（校验见 `SCHEMA_004`） | — |
| GET | `/classes/{class_id}/properties` | 属性表格数据 | `#schema-prop-tbody` |
| POST | `/classes/{class_id}/properties` | 新增属性 | `#schema-prop-modal` → `#schema-prop-confirm` |
| PATCH | `/properties/{property_id}` | 编辑属性（含跨类移动 domain） | 行内"编辑" |
| DELETE | `/properties/{property_id}` | 删除属性 | 行内"删除" |
| POST | `/schemas/{id}/induce` | AI Schema 归纳，前置依赖见 §2.2 | `#btn-schema-extract` |
| GET | `/schemas/{id}/export-ttl` | 返回 `text/turtle`（§9.1） | `#btn-export-ttl` |
| POST | `/schemas/import-ttl` | multipart `.ttl` 上传，事务化解析（§9.2） | `#schema-import-file` |

### 8.4 本体抽取（实例）

| Method | Path | 说明 | 原型触发点 |
|---|---|---|---|
| POST | `/extraction/instances/unstructured` | 见 `UnstructuredExtractionRequest` | "非结构化抽取" “启动 AI 抽取” |
| POST | `/extraction/instances/structured` | 见 `StructuredExtractionRequest` | "结构化抽取" “开始抽取” |
| GET | `/extraction/tasks/{id}` | 任务状态轮询 | 进度条区域 |
| GET | `/extraction/tasks/{id}/instances` | 结果分页预览 | "实例数据预览"表格 |
| GET | `/instances/{id}` | 实例详情（属性值 + 关系） | "实例详情"弹窗 / 图谱节点点击 |
| GET | `/schemas/{id}/instance-stats` | 按类统计实例数 | "抽取结果统计" |

### 8.5 结构化字段映射

| Method | Path | 说明 | 原型触发点 |
|---|---|---|---|
| GET | `/mappings/source-fields?table_id=` | 源表列清单 | 映射弹窗左侧"源字段" |
| GET | `/mappings/target-properties?class_id=` | 目标类属性清单（含伪属性"实例 URI"） | 映射弹窗右侧"目标属性" |
| GET | `/mappings?schema_id=&class_id=` | 查询已保存映射 | "已配置"提示 |
| POST | `/mappings` | 新建/覆盖保存映射及 binding | `#mapping-confirm` |

### 8.6 业务逻辑抽取

| Method | Path | 说明 | 原型触发点 |
|---|---|---|---|
| POST | `/extraction/business-logic` | 前置依赖见 §2.2 `BIZLOGIC_001` | "开始抽取" |
| GET | `/extraction/tasks/{id}/rules` | 抽取结果 | 结果 JSON 预览 |
| GET | `/business-logic-rules?schema_id=` | 查询已持久化规则 | — |
| GET | `/business-logic-rules/export?schema_id=&format=json` | 导出下载 | "导出文件" |

### 8.7 图谱探索

| Method | Path | 说明 | 原型触发点 |
|---|---|---|---|
| GET | `/graph?schema_id=&mode=mixed\|schema\|instance` | 返回 `GraphResponse`（§9.4） | `renderD3Graph(mode)` |
| GET | `/graph/nodes/{node_id}?node_type=class\|instance` | 节点详情 | `showNodeDetail(d)` |

### 8.8 首页统计

| Method | Path | 说明 |
|---|---|---|
| GET | `/dashboard/summary` | 数据源数、Schema 数、实例数、图谱数 |
| GET | `/dashboard/activity` | 最近动态列表 |

---

## 9. 核心业务逻辑设计

### 9.1 TTL 生成规则（`rdf/ttl_builder.py`）

```turtle
@prefix om: <http://example.com/ontomind/schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

om: a owl:Ontology .

om:Transformer a owl:Class ;
  rdfs:label "设备"@zh ;
  rdfs:subClassOf om:Equipment ;
  rdfs:comment "..."@zh .

om:deviceCode a owl:DatatypeProperty ;
  rdfs:label "设备编号"@zh ;
  rdfs:domain om:Transformer ;
  rdfs:range xsd:string .

om:belongsToLine a owl:ObjectProperty ;
  rdfs:label "属于产线"@zh ;
  rdfs:domain om:Transformer ;
  rdfs:range om:ProductionLine .
```

`local_name` 为空时，后端需将中文 `label` 转换为安全 IRI local name（转拼音或 URL-encode，需在 `ttl_builder.py` 中给出明确规则并写单元测试）。必须使用 `rdflib.Graph()` + `graph.serialize(format="turtle")`，不得手写字符串拼接。

### 9.2 TTL 导入（`rdf/ttl_parser.py`，★ 事务化）

用 `rdflib.Graph().parse(data=..., format="turtle")` 解析，遍历 `owl:Class`/`owl:DatatypeProperty`/`owl:ObjectProperty` 三元组。**整个"解析 → 校验 → 写库"过程必须包裹在单个数据库事务内**：

```python
async def import_ttl(session: AsyncSession, ttl_text: str) -> OntologySchema:
    try:
        graph = parse_ttl(ttl_text)          # 语法错误在此抛出，事务尚未开始，无需回滚
        classes, properties = extract_entities(graph)  # 语义校验：孤立属性、循环继承等
    except TtlSyntaxError as e:
        raise SchemaImportError(code="SCHEMA_003", message=f"TTL 文件解析失败：{e}")

    async with session.begin():              # 显式事务边界
        schema = await schema_repo.create(session, ...)
        await class_repo.bulk_create(session, classes)
        await property_repo.bulk_create(session, properties)
        # 事务块正常退出 -> COMMIT；块内任意异常 -> 自动 ROLLBACK，不留下部分导入的类/属性
    return schema
```

若 FastAPI 依赖注入的 `AsyncSession` 默认已按请求自动开启事务，则用 `SAVEPOINT`（`session.begin_nested()`）代替顶层 `begin()`，效果等价：任何一步失败，整个导入操作全部回滚，不允许出现"导入了一半的类"这种脏数据。

### 9.3 AI 抽取相关的文件处理

**转本体 MD**（`file_service.convert_to_ontology_md`）：在"转标准 MD"产出的干净 Markdown 基础上，识别章节标题、表格、候选实体/术语并做结构化标注，目的是降低后续 Schema 归纳与实例抽取阶段的 LLM 理解成本。产物写入 `ontology_md_path`，存储方式跟随原文件的 `storage_backend`。

**构建表 SQL**：优先用规则式表格检测（Markdown 表格语法或文档内识别到的表格结构）推断列名与类型，生成 `CREATE TABLE {slug} (...)` 预览；确认后 `materialize-table` 在专用 schema（如 `ontomind_generated`）执行 DDL 并批量 `INSERT`，写入 `data_source_table(is_generated=true)`，即可像普通数据库表一样进入"结构化字段映射"流程。

### 9.4 图谱数据组装（`graph_service.py`）

返回结构对齐原型 `graphData`：

```json
{
  "nodes": [
    {"id": "c_<uuid>", "type": "class", "label": "设备", "dp": 6, "op": 2, "inst": 823},
    {"id": "op_<uuid>", "type": "obj_prop", "label": "属于产线"},
    {"id": "dp_<uuid>", "type": "data_prop", "label": "设备编号"},
    {"id": "i_<uuid>", "type": "instance", "label": "GY-01", "classId": "c_<uuid>"}
  ],
  "links": [
    {"source": "c_<uuid>", "target": "op_<uuid>", "type": "schema_link"},
    {"source": "op_<uuid>", "target": "c_<uuid2>", "type": "schema_link"},
    {"source": "i_<uuid>", "target": "c_<uuid>", "type": "instance_of"},
    {"source": "i_<uuid>", "target": "i_<uuid3>", "label": "属于产线", "type": "instance_rel"}
  ]
}
```

组装规则：
- `mode=schema`：nodes = 全部 class + 全部 property（object/data property 各自展开为独立节点）；links 仅 `schema_link`。
- `mode=instance`：nodes = 全部 instance；links 由 `instance_relation` 生成 `instance_rel`。
- `mode=mixed`：合并以上两组节点/边，并补充 `instance_of` 边。
- 空数据不报错，返回空数组（见 §2.2）。
- 大数据量保护：默认 `?limit=500`，超出提示"数据量较大，建议按 Schema 缩小范围"。
- **缓存（可选）**：先查 `graph_cache(schema_id, mode)`，命中且未过期直接返回；未命中则组装后写入缓存。写操作触发的缓存失效见 §6.7。

### 9.5 结构化实例抽取（ETL，`extraction_service.run_structured`）
1. 读取 `field_mapping` + `field_mapping_binding`。
2. 通过 `data_source_db` 连接信息对源库分批 `SELECT ... LIMIT/OFFSET` 避免大表 OOM。
3. 每行：`target_kind='instance_uri'` 列值用作 `local_name`；其余列按 `target_property_id` 写入 `instance_data_value`（data）或创建/关联 `instance_relation`（object，需先按值查找/创建目标实例）。
4. 全程更新 `extraction_task.progress`。

---

## 10. AI 模块设计（★ 新增/大幅扩展）

### 10.1 统一响应信封

所有 `LLMProvider` 方法必须返回统一信封，便于后续切换 OpenAI / 通义千问 / DeepSeek / 华为盘古等任意兼容供应商而不影响调用方代码：

```python
T = TypeVar("T")

class AIResult(BaseModel, Generic[T]):
    success: bool
    result: T | None
    confidence: float | None    # 整体置信度 0~100，可为空
    tokens_used: int | None
    latency_ms: int | None
    error: str | None
```

```python
class LLMProvider(Protocol):
    async def induce_schema(self, texts: list[str], existing_classes: list[str]) -> AIResult["SchemaInductionResult"]: ...
    async def extract_instances(self, texts: list[str], schema_snapshot: "SchemaSnapshot") -> AIResult["InstanceExtractionResult"]: ...
    async def extract_business_logic(self, texts: list[str], schema_snapshot: "SchemaSnapshot", instance_labels: list[str]) -> AIResult[list["BusinessLogicRuleDraft"]]: ...
```

### 10.2 各任务的输入 / 输出契约

| 任务 | 输入 | 输出 |
|---|---|---|
| Schema 归纳 (`schema_induction`) | `texts`（多个文档的本体 MD 内容）、`existing_classes`（已有类名，避免重复归纳，支持增量建议） | `SchemaInductionResult = {classes: [{label, local_name, description, confidence}], properties: [{class_label, label, kind, datatype\|range_class_label, required, multi, confidence}]}` |
| 非结构化实例抽取 (`instance_unstructured`) | `texts`、`schema_snapshot`（类+属性定义，用作抽取约束） | `InstanceExtractionResult = {instances: [{class_label, label, local_name, source_ref, confidence, data_values:[{property_label, value}], relations:[{property_label, target_instance_label}]}]}` |
| 业务逻辑抽取 (`business_logic`) | `texts`（业务文档）、`schema_snapshot`、`instance_labels`（已知实例名，帮助模型把"主变压器"锚定到具体实体） | `list[BusinessLogicRuleDraft]`，字段结构与 §11.1 JSON 示例一致 |

### 10.3 Prompt 设计原则
1. **强制结构化输出**：要求模型只返回 JSON（`response_format={"type":"json_object"}` 或等效约束），字段名必须与对应 Pydantic 模型完全一致，便于直接 `model_validate_json` 反序列化。
2. **提供 few-shot 示例**：可直接复用 `frontendUCD.html` 中硬编码的示例数据（如"设备编号/运行状态/投运日期"、业务逻辑规则 JSON）作为提示词中的示例，保证输出风格与产品预期一致。
3. **校验失败重试**：LLM 返回的 JSON 经 Pydantic 校验，失败时最多重试 2 次（可调整提示词强调格式要求）；仍失败则该文件标记处理失败、记录 `error_message`，**不影响同批次其他文件**（任务整体仍可 `succeeded`，`output_summary` 中体现"成功 N / 失败 M"）。
4. **置信度来源**：优先要求模型自评置信度；若供应商不支持，可退化为固定默认值（如 80），并在 `AIResult.confidence` 中如实标注该值为"估算值"（后端日志记录，不需要暴露给前端）。

### 10.4 MockLLMProvider 行为约定
- 默认启用（`LLM_PROVIDER=mock`），对任意输入返回预置的固定/伪随机示例结果（复用原型中设备/产线/供应商等示例数据）。
- 模拟真实延迟：`await asyncio.sleep(random.uniform(0.3, 0.9))`，使前端进度条呈现真实的渐进观感，而不是瞬间跳到 100%。
- 真实 Provider 在 `ai/openai_compatible_provider.py` 中实现同一接口，通过 `LLM_PROVIDER=openai_compatible` + `LLM_API_BASE`/`LLM_API_KEY`/`LLM_MODEL` 切换，作为 §13 Phase 8 的独立任务接入，不阻塞其余模块开发。

---

## 11. 前端架构（Angular 20+）

### 11.1 目录结构

```
frontend/
  src/app/
    app.config.ts
    app.routes.ts
    core/
      api/
        api-client.ts
        interceptors/
          error.interceptor.ts     # 捕获 ErrorResponse，field 存在时联动表单 setErrors
      models/                       # 与后端 §7.3 DTO 一一对应的 TS interface
      services/
        toast.service.ts
        confirm-dialog.service.ts
    shared/
      ui/
        button/  badge/  data-table/  modal/  dropzone/  action-menu/
        stat-card/  pipeline-step/  progress-bar/  code-block/
      pipes/
        file-size.pipe.ts
        relative-time.pipe.ts
    features/
      dashboard/
      data-integration/
        structured/
        unstructured/
      schema-studio/
      extraction/
        instance-extraction/
        business-logic/
      graph-explorer/
    styles/
      tokens.scss                   # 从 frontendUCD.html :root 变量 1:1 迁移
      base.scss
  angular.json
  package.json
```

### 11.2 关键约定
- 一律 **Standalone Component**，不使用 `NgModule`。
- **状态管理用 Signals**，不引入 NgRx：每个 feature 一个 `*.store.ts`。
- **HTTP 层**：每个后端资源对应一个 `*.api.ts`，`store` 内转换为 signal。
- **弹窗表单**：统一 `ReactiveFormsModule`；错误处理与后端 `ErrorDetail.field` 联动（见 §7.4）。
- **D3 力导向图**：`d3-force-graph.component.ts` 移植原型 `renderD3Graph()`/`showNodeDetail()` 逻辑，样式常量从 `tokens.scss` 读取。
- **设计系统**：原型 `:root` CSS 变量原样迁移到 `tokens.scss`。
- **图标**：沿用 `lucide-angular`，图标名与原型 `data-lucide` 一致。

### 11.3 路由与懒加载
```ts
export const routes: Routes = [
  { path: '', loadComponent: () => import('./features/dashboard/dashboard.page').then(m => m.DashboardPage) },
  { path: 'data/structured', loadComponent: () => import('./features/data-integration/structured/structured.page').then(m => m.StructuredPage) },
  { path: 'data/unstructured', loadComponent: () => import('./features/data-integration/unstructured/unstructured.page').then(m => m.UnstructuredPage) },
  { path: 'schema', loadComponent: () => import('./features/schema-studio/schema-studio.page').then(m => m.SchemaStudioPage) },
  { path: 'extraction/instances', loadComponent: () => import('./features/extraction/instance-extraction/instance-extraction.page').then(m => m.InstanceExtractionPage) },
  { path: 'extraction/business-logic', loadComponent: () => import('./features/extraction/business-logic/business-logic.page').then(m => m.BusinessLogicPage) },
  { path: 'graph', loadComponent: () => import('./features/graph-explorer/graph-explorer.page').then(m => m.GraphExplorerPage) },
];
```

---

## 12. 编码规范（Coding Convention，★ 新增）

Agent 在生成任何后端代码前必须遵守以下硬性规则，这些规则的价值在于**减少代码风格随机性、提高多次生成之间的一致性**：

1. Router 层禁止出现任何 `session.execute` / ORM 查询，一律经 Service。
2. Service 层返回值必须是 Pydantic DTO，禁止把 SQLAlchemy ORM 对象直接返回给 Router（用 `XxxRead.model_validate(orm_obj)` 转换）。
3. Repository 层禁止 `import app.ai` / `app.storage` / `app.rdf`。
4. 禁止循环内逐条执行 SQL（N+1）；批量操作用 `execute(insert(...), list_of_dicts)` 或 `selectinload` 预加载。
5. 所有写操作的 Service 方法必须在同一个 `AsyncSession` 事务内完成；禁止内部再开独立子事务，除非明确需要 `SAVEPOINT`（如 §9.2 TTL 导入）。
6. 所有时间统一 UTC 存储与传输（`TIMESTAMPTZ` + ISO8601），代码中禁止出现 `datetime.now()`，一律 `datetime.now(timezone.utc)`；本地化展示是前端职责。
7. 所有主键统一 `UUID`，禁止自增整数主键。
8. 所有列表接口必须支持分页并返回 `total`，禁止无限制 `SELECT *`。
9. 所有 Enum 值统一小写英文 + 下划线（如 `instance_unstructured`），禁止中文或驼峰值存入数据库。
10. 所有异常必须携带 §7.4 定义的 `ErrorCode`，禁止裸抛不带 code 的异常。
11. 新增字段如涉及枚举，必须同步更新本文档 §6 DDL 中的 `CHECK` 约束与 §7.4 错误码表，保持文档与代码同步（Agent 自检项，非强制工具校验）。
12. 前端组件禁止直接拼接后端 URL 字符串，统一通过 `core/api/*.api.ts` 封装。
13. 前端所有弹窗表单的校验错误提示文案，必须与后端 `ErrorDetail.message` 保持一致（不允许前端另写一套文案）。

---

## 13. 建议实施顺序（里程碑）

严格按依赖顺序推进（依据 §2 的全局依赖关系），每个阶段完成后应可独立跑通、可演示：

1. **Phase 0 — 基建**：初始化工程；Alembic 首个迁移覆盖 §6 全部 DDL；确定 §7.4 错误码枚举与 §12 编码规范作为团队/Agent 基线；Angular 路由骨架 + 侧边栏导航（静态可切换七个空页面）。
2. **Phase 1 — 业务数据集成**：`db-sources`、`files` 全部接口 + 前端两个页面（含全部弹窗、上传、重命名、删除确认）。此阶段不需要真实文件解析，`extracted_text` 可先存占位文本。
3. **Phase 2 — Schema 模块**：类/属性 CRUD、状态机（§5.4）、TTL 导入导出（`rdflib` 必须打通，事务化，§9.2）。AI 归纳先接 `MockLLMProvider`。
4. **Phase 3 — 结构化字段映射 + 结构化实例抽取**：确定性 ETL，不依赖 LLM，优先跑通，验证 §9.5 全链路与 §2.2 依赖校验。
5. **Phase 4 — 非结构化实例抽取**：接入 `MockLLMProvider`，跑通 §2.3 异步任务时序与状态机（§5.1）。
6. **Phase 5 — 业务逻辑抽取**：同样先用 Mock，验证 §11.1 JSON 结构与导出，校验 `BIZLOGIC_001` 前置依赖。
7. **Phase 6 — 图谱探索**：`graph_service` + D3 组件；此时 Schema/实例数据已具备，可直接可视化验证前几阶段数据正确性。
8. **Phase 7 — 首页统计与最近动态**：依赖前面模块数据已存在，最后实现最容易验证。
9. **Phase 8 — 真实能力接入**：真实 `LLMProvider`（§10.4）、MinIO 真实对接、文档解析（`pypdf`/`python-docx`/`unstructured`）、构建表 SQL 的真实表格检测算法。
10. **Phase 9 — 联调与加固**：错误态/空态统一走查（对照原型 `empty-state`、`b-danger` 状态徽章）、并发与大数据量分页/限流、图谱缓存（§6.7，可选）、pytest 覆盖 Service 层（重点覆盖 §5 状态机的非法转换应被拒绝、§2.2 依赖校验、§9.2 TTL 导入事务回滚）。

---

## 14. 非功能性约定

- **无鉴权**：所有路由不加 `Depends(get_current_user)`；表结构预留 `created_by`/`published_by` 等可空字段。
- **CORS**：开发环境 `allow_origins=["*"]`，生产环境改为具体域名。
- **分页**：统一 `?page=1&page_size=20`，响应 `PageResponse`（§7.3）。
- **时间序列化**：统一 ISO 8601 UTC，前端本地化展示。
- **日志**：标准 `logging`，关键动作（连接测试、任务开始/结束、TTL 导入导出）落 INFO，异常落 ERROR 并带 `task_id`/`resource_id` 上下文。
- **环境变量清单**（`.env.example`）：
  ```
  DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/ontomind
  DB_SECRET_KEY=
  LOCAL_STORAGE_ROOT=./data/uploads
  MINIO_ENDPOINT=
  MINIO_ACCESS_KEY=
  MINIO_SECRET_KEY=
  MINIO_BUCKET=ontomind
  LLM_PROVIDER=mock              # mock | openai_compatible
  LLM_API_BASE=
  LLM_API_KEY=
  LLM_MODEL=
  ```

---

## 15. 附录

### 15.1 业务逻辑规则 JSON 输出结构

```json
{
  "business_logic": [
    {
      "rule_id": "rule_001",
      "type": "causality",
      "description": "当主变压器油温超过85度时，可能导致绝缘老化加速，引发轻瓦斯报警。",
      "condition": { "subject": "主变压器", "attribute": "油温", "operator": ">", "value": "85℃" },
      "consequence": ["绝缘老化加速", "轻瓦斯报警"],
      "source_doc": "断路器异常跳闸分析报告.docx"
    },
    {
      "rule_id": "rule_002",
      "type": "constraint",
      "description": "断路器SF6气体压力低于0.4MPa时，必须立即闭锁分合闸操作。",
      "condition": { "subject": "断路器", "attribute": "SF6气体压力", "operator": "<", "value": "0.4MPa" },
      "action_required": "闭锁分合闸操作",
      "severity": "critical",
      "source_doc": "2026年Q1变压器检修工单.pdf"
    }
  ]
}
```

### 15.2 与原型的对照检查清单

Agent 完成每个模块后，应逐条对照 `frontendUCD.html` 中该 view 的以下要素：
- [ ] 表格列是否与本文档 DDL 字段一一对应
- [ ] 每个按钮/图标（`data-lucide` 属性值）是否都有对应的接口调用
- [ ] 每个弹窗的必填校验规则、报错文案是否与 §7.4 错误码表一致
- [ ] 状态徽章（成功/警告/失败/中性）的取值范围是否与 §5 状态机、§6 DDL 枚举一致
- [ ] 异步操作（上传、抽取）是否有对应的进度反馈与 toast 提示，是否符合 §2.3 时序图

### 15.3 评审意见采纳说明

本 v2 相较 v1 采纳了以下评审建议：系统业务流程图、状态机设计、Service/Repository 职责边界、DTO 契约、统一错误码、AI 模块设计扩展、编码规范。以下建议经评估后**未采纳或调整为可选**，原因一并说明：
- **Celery/Redis 任务队列**：当前任务量级不需要分布式队列，强行引入会增加部署复杂度；已在 §7.5 保留平滑升级路径。
- **图谱 Redis 缓存**：改为纯 Postgres 的 `graph_cache` 表（§6.7），避免引入新的基础设施依赖，效果等价（失效式缓存）。
- **Schema 发布后锁定/分支模型**：评估后判断超出当前范围，采用更轻量的"版本号 + change_log 快照"方案（§5.4），完整分支/Diff 机制留待后续独立设计。

---

*文档结束。如实现过程中发现原型交互与本文档描述存在冲突，以本文档的数据结构设计为准、以原型的视觉与文案为准；若冲突无法调和，请在对应模块代码中添加 `// TODO(spec-conflict): ...` 注释并继续推进，不应阻塞整体进度。*
