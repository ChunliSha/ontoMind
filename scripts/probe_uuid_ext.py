"""Probe UUID-related extensions on the configured DATABASE_URL."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import asyncpg

ENV = Path(__file__).resolve().parent.parent / ".env"


def load_dsn() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return re.sub(
                r"^postgresql\+asyncpg://",
                "postgresql://",
                line.split("=", 1)[1].strip(),
            )
    raise SystemExit("DATABASE_URL not found")


async def main() -> None:
    conn = await asyncpg.connect(load_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT name, installed_version, default_version
            FROM pg_available_extensions
            WHERE name IN ('pgcrypto', 'uuid-ossp')
            ORDER BY name
            """
        )
        if not rows:
            print("no pgcrypto/uuid-ossp in pg_available_extensions")
        for row in rows:
            print(dict(row))

        for ext in ("uuid-ossp", "pgcrypto"):
            tx = conn.transaction()
            await tx.start()
            try:
                await conn.execute(f'CREATE EXTENSION "{ext}"')
                print(f"{ext}: CREATE OK (rolled back)")
            except Exception as exc:  # noqa: BLE001
                print(f"{ext}: FAIL — {exc}")
            finally:
                await tx.rollback()
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
