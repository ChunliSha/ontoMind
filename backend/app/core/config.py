"""Application settings loaded from repo-root `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py → repo root is parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    # If empty in .env, a stable local-dev key is used so Fernet still works.
    # Generate a real key for shared/prod: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    DB_SECRET_KEY: str = ""
    LOCAL_STORAGE_ROOT: str = "./data/uploads"
    MINIO_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = "ontomind"
    # None = infer from MINIO_ENDPOINT scheme (https → true, otherwise false)
    MINIO_SECURE: bool | None = None
    LLM_PROVIDER: str = "openai_compatible"  # openai_compatible
    LLM_API_BASE: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    CORS_ORIGINS: str = "*"

    @property
    def local_storage_path(self) -> Path:
        root = Path(self.LOCAL_STORAGE_ROOT)
        if not root.is_absolute():
            root = _REPO_ROOT / root
        return root

    @property
    def fernet_key(self) -> bytes:
        import base64
        import hashlib

        key = (self.DB_SECRET_KEY or "").strip()
        if key:
            return key.encode("utf-8")
        # Stable local-dev Fernet key derived from a fixed seed (NOT for production).
        raw = hashlib.sha256(b"ontomind-local-dev-secret").digest()
        return base64.urlsafe_b64encode(raw)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
