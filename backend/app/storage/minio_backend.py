"""MinIO object storage backend (S3-compatible)."""

from __future__ import annotations

import asyncio
from io import BytesIO
from urllib.parse import urlparse

from app.core.config import settings
from app.core.exceptions import AppError, ErrorCode


def parse_minio_endpoint(raw: str) -> tuple[str, bool]:
    """Return (host:port, use_tls). Accepts `host:9000` or `http(s)://host:9000`."""
    value = (raw or "").strip()
    if not value:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            message="MinIO 尚未配置（MINIO_ENDPOINT 为空），请在仓库根目录 .env 中填写后重启后端",
        )
    if "://" not in value:
        return value, False
    parsed = urlparse(value)
    host = parsed.netloc or parsed.path
    if not host:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            message=f"MINIO_ENDPOINT 无效：{raw}",
        )
    return host, parsed.scheme == "https"


class MinIOStorageBackend:
    def __init__(self) -> None:
        endpoint, inferred_tls = parse_minio_endpoint(settings.MINIO_ENDPOINT)
        access_key = (settings.MINIO_ACCESS_KEY or "").strip()
        secret_key = (settings.MINIO_SECRET_KEY or "").strip()
        if not access_key or not secret_key:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                message="MinIO 密钥未配置（MINIO_ACCESS_KEY / MINIO_SECRET_KEY 为空），请填写 .env 后重启后端",
            )
        self.endpoint = endpoint
        self.secure = bool(settings.MINIO_SECURE) if settings.MINIO_SECURE is not None else inferred_tls
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = (settings.MINIO_BUCKET or "ontomind").strip() or "ontomind"
        self._client = None

    def _client_sync(self):
        if self._client is None:
            from minio import Minio

            self._client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
        return self._client

    def _ensure_bucket(self) -> None:
        client = self._client_sync()
        if not client.bucket_exists(self.bucket):
            client.make_bucket(self.bucket)

    def _wrap_s3(self, exc: Exception) -> AppError:
        return AppError(
            ErrorCode.INTERNAL_ERROR,
            message=f"MinIO 操作失败（{self.endpoint}/{self.bucket}）：{exc}",
        )

    async def save(self, key: str, content: bytes, content_type: str) -> str:
        def _put() -> None:
            try:
                self._ensure_bucket()
                self._client_sync().put_object(
                    self.bucket,
                    key,
                    BytesIO(content),
                    length=len(content),
                    content_type=content_type or "application/octet-stream",
                )
            except AppError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise self._wrap_s3(exc) from exc

        await asyncio.to_thread(_put)
        return key

    async def read(self, key: str) -> bytes:
        def _get() -> bytes:
            try:
                response = self._client_sync().get_object(self.bucket, key)
                try:
                    return response.read()
                finally:
                    response.close()
                    response.release_conn()
            except Exception as exc:  # noqa: BLE001
                raise self._wrap_s3(exc) from exc

        return await asyncio.to_thread(_get)

    async def delete(self, key: str) -> None:
        def _del() -> None:
            try:
                self._client_sync().remove_object(self.bucket, key)
            except Exception as exc:  # noqa: BLE001
                raise self._wrap_s3(exc) from exc

        await asyncio.to_thread(_del)

    async def url(self, key: str) -> str:
        scheme = "https" if self.secure else "http"
        return f"{scheme}://{self.endpoint}/{self.bucket}/{key}"
