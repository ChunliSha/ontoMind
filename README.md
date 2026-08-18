# OntoMind · 本体抽取工作台

基于 [OntoMind-软件开发指导文档.md](OntoMind-软件开发指导文档.md) 与 [frontendUCD.html](frontendUCD.html) 实现的全栈 MVP。

| 层 | 技术 |
|---|---|
| 前端 | Angular 20（Standalone + Signals）+ D3 + lucide |
| 后端 | FastAPI + SQLAlchemy 2 async + Alembic |
| 数据库 | PostgreSQL 15+（远程直连） |
| AI | OpenAI 兼容 LLM（`populate_ontology` Semantica 流水线） |

## 快速启动

### 1. 环境

- Python 3.12 + 仓库根目录 `.venv`
- Node.js 22.12+（本机可放在 `D:\tools\node-v22.12.0-win-x64`）
- 根目录 `.env`（从 `.env.example` 复制），至少配置：

```
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
DB_SECRET_KEY=<Fernet key>
LLM_PROVIDER=openai_compatible
LOCAL_STORAGE_ROOT=./data/uploads
```

生成密钥：

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

若本机开着 Clash Verge TUN，请为内网段加前置规则：`IP-CIDR,172.16.0.0/12,DIRECT,no-resolve`。

### 2. 数据库迁移

```powershell
cd backend
$env:PYTHONPATH = (Get-Location).Path
..\.\.venv\Scripts\python.exe -m alembic upgrade head
```

首个迁移会执行 `CREATE EXTENSION IF NOT EXISTS pgcrypto` 并创建全部业务表。

### 3. 启动后端

```powershell
cd backend
$env:PYTHONPATH = (Get-Location).Path
..\.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- API 文档：http://127.0.0.1:8000/docs  
- 健康检查：http://127.0.0.1:8000/health  

### 4. 启动前端

```powershell
$env:Path = 'D:\tools\node-v22.12.0-win-x64;' + $env:Path
cd frontend
npm start
```

浏览器打开 http://127.0.0.1:4200/ 。前端默认请求 `http://localhost:8000/api/v1`。

## 功能模块 ↔ 路由

| 页面 | 前端路由 | 主要后端资源 |
|---|---|---|
| 快速指引 | `/` | `/dashboard/*` |
| 非结构化数据 | `/data/unstructured` | `/files` |
| 结构化数据 | `/data/structured` | `/db-sources` |
| Schema 设计 | `/schema` | `/schemas`、`/classes`、`/properties` |
| 本体抽取 | `/extraction/instances` | `/extraction/instances/*`、`/mappings` |
| 业务逻辑抽取 | `/extraction/business-logic` | `/extraction/business-logic`、`/business-logic-rules` |
| 图谱探索 | `/graph` | `/graph` |

## 工程结构

```
backend/app/     # FastAPI：router → service → repository → ORM
frontend/src/app # Angular：features + shared UI + core/api
scripts/         # 环境自检（verify_db.py）
```

分层与错误码、状态机、DTO 契约以软件开发指导文档为准。

## 测试

```powershell
cd backend
$env:PYTHONPATH = (Get-Location).Path
..\.\.venv\Scripts\python.exe -m pytest tests/unit -q
```

## 已知边界（MVP）

- 文档解析为占位文本，真实 PDF/DOCX / MinIO / 生产 LLM 接入见规划 Phase 8
- 异步任务使用进程内 `asyncio`；重启时会把残留 `running` 任务标记为 `failed`
- 图谱工具栏使用 Schema 选择器（与原型 TTL 选择器的差异已标注 `TODO(spec-conflict)`）

更细的阶段划分与验收标准见 [OntoMind-开发规划.md](OntoMind-开发规划.md)。
