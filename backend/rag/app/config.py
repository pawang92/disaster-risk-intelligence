from functools import lru_cache
from os import getenv

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the local-first disaster-risk RAG service."""

    model_config = SettingsConfigDict(
        env_file=getenv("ENV_FILE", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ============================================================
    # LLM / Answer Generation
    # ============================================================

    # Supported: grok | gemini | ollama
    answer_provider: str = "grok"

    # ----------------------------
    # Grok / xAI
    # ----------------------------
    grok_api_key: str = ""
    grok_base_url: str = "https://api.x.ai/v1"
    grok_model: str = "grok-4.6"
    grok_timeout_seconds: float = 180.0

    # ----------------------------
    # Ollama - Local fallback
    # ----------------------------
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma3:4b"
    ollama_timeout_seconds: float = 180.0

    # ----------------------------
    # Gemini - Optional fallback
    # ----------------------------
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 180.0

    # ============================================================
    # Embeddings
    # ============================================================

    # Recommended for local/free development:
    # local
    #
    # Optional:
    # bedrock
    embedding_provider: str = "local"

    local_embedding_model: str = "intfloat/multilingual-e5-base"

    # Used only when Bedrock embedding is enabled.
    embedding_dimensions: int = 1024
    embedding_min_interval_seconds: float = 8.0
    embedding_max_attempts: int = 8

    # ============================================================
    # ChromaDB
    # ============================================================

    chroma_collection: str = "disaster-guidance"
    chroma_path: str = "./.chroma"

    # ============================================================
    # Retrieval
    # ============================================================

    retrieval_k: int = 6
    max_context_characters: int = 12000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached application settings instance."""
    return Settings()