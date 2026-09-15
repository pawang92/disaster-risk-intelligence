from functools import lru_cache
from os import getenv

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the local-first disaster-risk RAG service."""

    model_config = SettingsConfigDict(
        env_file=getenv("ENV_FILE", ".env"),
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # AWS
    # ------------------------------------------------------------------
    # Kept for optional future Bedrock usage.
    aws_region: str = "ap-south-1"

    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"

    bedrock_chat_model_id: str = (
        "anthropic.claude-3-haiku-20240307-v1:0"
    )

    # ------------------------------------------------------------------
    # Answer generation
    # ------------------------------------------------------------------
    # Local development:
    # ollama = use local Ollama only
    # bedrock = use AWS Bedrock only
    # auto = Bedrock first, Ollama fallback
    answer_provider: str = "ollama"

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------
    ollama_base_url: str = "http://127.0.0.1:11434"

    ollama_model: str = "gemma3:4b"

    ollama_timeout_seconds: float = 180.0

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    # Local embedding avoids Bedrock embedding costs/throttling.
    embedding_provider: str = "local"

    local_embedding_model: str = (
        "intfloat/multilingual-e5-base"
    )

    # Used only by Bedrock embedding.
    embedding_dimensions: int = 1024

    # Used only by Bedrock embedding.
    embedding_min_interval_seconds: float = 8.0

    embedding_max_attempts: int = 8

    # ------------------------------------------------------------------
    # Chroma
    # ------------------------------------------------------------------
    chroma_collection: str = "disaster-guidance"

    chroma_path: str = "./.chroma"

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    retrieval_k: int = 6

    max_context_characters: int = 12000

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    debug: bool = False

    # ------------------------------------------------------------------
    # S3
    # ------------------------------------------------------------------
    source_bucket: str = ""

    source_prefix: str = "documents/"


@lru_cache
def get_settings() -> Settings:
    return Settings()