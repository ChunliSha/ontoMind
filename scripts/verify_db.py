"""远程 PostgreSQL 16 环境校验（Phase -1）。

校验开发指导文档 §6 全部 DDL 与 §9.3「构建表 SQL」落地所依赖的三项前提：
  1. asyncpg 能直连目标库；
  2. pgcrypto 扩展可用（gen_random_uuid() 是所有主键默认值的前提）；
  3. 当前账号有 CREATE SCHEMA 权限（materialize-table 需要 ontomind_generated）。

用法：
    python scripts/verify_db.py                     # 从 .env 读取 DATABASE_URL
    python scripts/verify_db.py <postgres-dsn>      # 直接传 DSN

所有探测均在事务中进行且最终回滚，不会在目标库留下任何对象。
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import asyncpg

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
GENERATED_SCHEMA = "ontomind_generated"

OK = "[ OK ]"
FAIL = "[FAIL]"
WARN = "[WARN]"


def load_dsn() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1].strip()

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    sys.exit(
        "未找到 DATABASE_URL。请在 .env 中配置，或作为命令行参数传入：\n"
        "    python scripts/verify_db.py postgresql://user:pass@host:5432/ontomind"
    )


def to_asyncpg_dsn(dsn: str) -> str:
    """SQLAlchemy 风格的 postgresql+asyncpg:// 前缀 asyncpg 本身不认，需剥离。"""
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", dsn)


def redact(dsn: str) -> str:
    return re.sub(r"://([^:/@]+):([^@]*)@", r"://\1:***@", dsn)


async def main() -> int:
    raw_dsn = load_dsn()
    dsn = to_asyncpg_dsn(raw_dsn)
    print(f"目标库：{redact(dsn)}\n")

    failures: list[str] = []

    # --- 1. 连通性 ---
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=15)
    except Exception as exc:  # noqa: BLE001 - 需要把任何连接失败原因原样呈现给使用者
        print(f"{FAIL} 1/4 连通性：无法连接 —— {type(exc).__name__}: {exc}")
        return 1

    try:
        version = await conn.fetchval("SHOW server_version")
        current_user = await conn.fetchval("SELECT current_user")
        database = await conn.fetchval("SELECT current_database()")
        print(f"{OK} 1/4 连通性：已连接 {database}，账号 {current_user}")

        major = int(version.split(".")[0])
        if major >= 16:
            print(f"{OK} 2/4 版本：PostgreSQL {version}")
        elif major >= 15:
            print(f"{WARN} 2/4 版本：PostgreSQL {version}（文档要求 15+，规划按 16 编写）")
        else:
            print(f"{FAIL} 2/4 版本：PostgreSQL {version}，低于要求的 15+")
            failures.append("版本过低")

        # --- 3. pgcrypto ---
        installed = await conn.fetchval(
            "SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto'"
        )
        if installed:
            uuid_value = await conn.fetchval("SELECT gen_random_uuid()")
            print(f"{OK} 3/4 pgcrypto：已安装，gen_random_uuid() 返回 {uuid_value}")
        else:
            available = await conn.fetchval(
                "SELECT 1 FROM pg_available_extensions WHERE name = 'pgcrypto'"
            )
            if not available:
                print(f"{FAIL} 3/4 pgcrypto：服务端未提供该扩展，需由 DBA 安装 contrib 包")
                failures.append("pgcrypto 不可用")
            else:
                # 尝试安装后回滚，仅用于探测权限，不真正改变目标库
                tx = conn.transaction()
                await tx.start()
                try:
                    await conn.execute("CREATE EXTENSION pgcrypto")
                    print(f"{OK} 3/4 pgcrypto：未安装，但当前账号有权限创建（探测后已回滚）")
                except Exception as exc:  # noqa: BLE001
                    print(f"{FAIL} 3/4 pgcrypto：未安装且当前账号无权创建 —— {exc}")
                    failures.append("pgcrypto 无法创建")
                finally:
                    await tx.rollback()

        # --- 4. CREATE SCHEMA ---
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(f'CREATE SCHEMA "{GENERATED_SCHEMA}_probe"')
            print(f"{OK} 4/4 CREATE SCHEMA：有权限（探测 schema 已回滚）")
        except Exception as exc:  # noqa: BLE001
            print(f"{FAIL} 4/4 CREATE SCHEMA：无权限 —— {exc}")
            print(f"       影响：§9.3 的 materialize-table 无法创建 {GENERATED_SCHEMA}")
            failures.append("无 CREATE SCHEMA 权限")
        finally:
            await tx.rollback()
    finally:
        await conn.close()

    print()
    if failures:
        print(f"{FAIL} 校验未通过：{('、').join(failures)}")
        return 1
    print(f"{OK} 全部校验通过，可以进入 Phase 0 建立 Alembic 首个迁移")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
