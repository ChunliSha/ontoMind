from app.storage.base import StorageBackend
from app.storage.local_backend import LocalStorageBackend
from app.storage.minio_backend import MinIOStorageBackend


def get_storage(backend: str = "local") -> StorageBackend:
    if backend == "minio":
        return MinIOStorageBackend()
    return LocalStorageBackend()


__all__ = ["StorageBackend", "LocalStorageBackend", "MinIOStorageBackend", "get_storage"]
