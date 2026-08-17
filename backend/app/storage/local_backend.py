"""Local filesystem storage backend."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import settings


class LocalStorageBackend:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.local_storage_path
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def save(self, key: str, content: bytes, content_type: str) -> str:
        path = self._path(key)

        def _write() -> None:
            path.write_bytes(content)

        await asyncio.to_thread(_write)
        return key

    async def read(self, key: str) -> bytes:
        path = self._path(key)

        def _read() -> bytes:
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    async def delete(self, key: str) -> None:
        path = self._path(key)

        def _del() -> None:
            if path.exists():
                path.unlink()

        await asyncio.to_thread(_del)

    async def url(self, key: str) -> str:
        return str(self._path(key))
