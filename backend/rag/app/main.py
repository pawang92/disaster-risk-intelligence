from functools import lru_cache
import logging

from fastapi import FastAPI, HTTPException

from .bedrock_rag import DisasterRag
from .config import get_settings
from .ingest import language_of
from .schema import AskRequest, AskResponse, HealthResponse

app = FastAPI(title="Disaster Risk Intelligence RAG", version="0.1.0")
logger = logging.getLogger(__name__)


@lru_cache
def rag() -> DisasterRag:
    return DisasterRag(get_settings())


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", store=settings.chroma_collection)


@app.post("/v1/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    filters = {key: value for key, value in {"district": payload.district, "disaster_type": payload.disaster_type}.items() if value}
    try:
        chunks = rag().retrieve(payload.question, filters or None)
        if not chunks:
            return AskResponse(answer="No relevant information was found in the indexed documents.", language=payload.language, citations=[])
        language = language_of(payload.question) if payload.language == "auto" else payload.language
        return AskResponse(answer=rag().answer(payload.question, language, chunks), language=language,
                           citations=[chunk.citation() for chunk in chunks])
    except Exception as exc:
        logger.exception("RAG request failed")
        detail = str(exc) if get_settings().debug else "RAG service is temporarily unavailable"
        raise HTTPException(status_code=503, detail=detail) from exc
