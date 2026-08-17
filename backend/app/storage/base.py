"""Storage backend protocol and factory."""

from __future__ import annotations

from typing import Protocol


class StorageBackend(Protocol):
    async def save(self, key: str, content: bytes, content_type: str) -> str: ...

    async def read(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def url(self, key: str) -> str: ...
