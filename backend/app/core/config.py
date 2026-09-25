from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the Disaster Risk Intelligence backend."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Disaster Risk Intelligence"
    app_version: str = "0.1.0"
    environment: str = "local"
    debug: bool = False

    api_prefix: str = "/api/v1"
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    postgis_url: str = "postgresql+psycopg://disaster:disaster@localhost:5432/disaster"
    redis_url: str = "redis://localhost:6379/0"

    default_hazard: str = "flood"
    risk_engine_version: str = "0.1.0"

    llm_provider: str = "grok"
    llm_fallbacks: str = "gemini,ollama"

    rag_base_url: str = "http://127.0.0.1:8001"

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def fallback_providers(self) -> list[str]:
        return [item.strip() for item in self.llm_fallbacks.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
