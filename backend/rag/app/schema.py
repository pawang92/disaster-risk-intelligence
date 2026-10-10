from typing import Any, Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    document_id: str
    source_key: str
    page: int = Field(ge=1)
    excerpt: str
    score: float | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    language: Literal["auto", "en", "mr"] = "auto"
    district: str | None = None
    disaster_type: str | None = None


class AskResponse(BaseModel):
    answer: str
    language: str
    citations: list[Citation]


class HealthResponse(BaseModel):
    status: str
    store: str
    collection: str
    collection_count: int
    embedding_provider: str
    answer_provider: str


class RetrievalTestRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    district: str | None = None
    disaster_type: str | None = None


class RetrievalTestResponse(BaseModel):
    diagnostics: dict[str, Any]
