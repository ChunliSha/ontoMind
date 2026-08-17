"""MinIO storage backend skeleton (Phase 8)."""

from __future__ import annotations

from app.core.config import settings
from app.core.exceptions import AppError, ErrorCode


class MinIOStorageBackend:
    """Skeleton — real MinIO client wiring is Phase 8."""

    def __init__(self) -> None:
        self.endpoint = settings.MINIO_ENDPOINT
        self.access_key = settings.MINIO_ACCESS_KEY
        self.secret_key = settings.MINIO_SECRET_KEY
        self.bucket = settings.MINIO_BUCKET

    def _ensure_configured(self) -> None:
        if not self.endpoint:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                message="MinIO 尚未配置（MINIO_ENDPOINT 为空），请使用 local 存储或完成 Phase 8 接入",
            )

    async def save(self, key: str, content: bytes, content_type: str) -> str:
        self._ensure_configured()
        raise AppError(ErrorCode.INTERNAL_ERROR, message="MinIOStorageBackend 尚未实现")

    async def read(self, key: str) -> bytes:
        self._ensure_configured()
        raise AppError(ErrorCode.INTERNAL_ERROR, message="MinIOStorageBackend 尚未实现")

    async def delete(self, key: str) -> None:
        self._ensure_configured()
        raise AppError(ErrorCode.INTERNAL_ERROR, message="MinIOStorageBackend 尚未实现")

    async def url(self, key: str) -> str:
        self._ensure_configured()
        return f"{self.endpoint}/{self.bucket}/{key}"
