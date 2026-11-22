from functools import lru_cache
import logging

from fastapi import FastAPI, HTTPException

from .disaster_rag import DisasterRag
from .config import get_settings
from .ingest import language_of
from .schema import (
    AskRequest,
    AskResponse,
    HealthResponse,
    RetrievalTestRequest,
    RetrievalTestResponse,
)
from .workflow import build_rag_graph

app = FastAPI(
    title="Disaster Risk Intelligence RAG",
    version="0.3.0",
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def rag() -> DisasterRag:
    return DisasterRag(get_settings())


@lru_cache(maxsize=1)
def rag_workflow():
    """Reuse the compiled graph and its underlying RAG service."""
    return build_rag_graph(rag())


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    collection = rag().chroma_collection

    return HealthResponse(
        status="ok",
        store="chroma",
        collection=collection.name,
        collection_count=collection.count(),
        embedding_provider=settings.embedding_provider,
        answer_provider=settings.answer_provider,
    )


@app.post("/v1/retrieval-test", response_model=RetrievalTestResponse)
def retrieval_test(payload: RetrievalTestRequest) -> RetrievalTestResponse:
    settings = get_settings()
    if not settings.debug:
        raise HTTPException(status_code=404, detail="Not found")

    filters = {
        key: value
        for key, value in {
            "district": payload.district,
            "disaster_type": payload.disaster_type,
        }.items()
        if value and value.strip()
    }

    try:
        diagnostics = rag().retrieval_diagnostics(
            payload.question,
            filters or None,
        )
        return RetrievalTestResponse(diagnostics=diagnostics)
    except Exception as exc:
        logger.exception("Retrieval diagnostics failed")
        detail = str(exc) if settings.debug else "Retrieval diagnostics unavailable"
        raise HTTPException(status_code=503, detail=detail) from exc


@app.post("/v1/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    filters = {
        key: value
        for key, value in {
            "district": payload.district,
            "disaster_type": payload.disaster_type,
        }.items()
        if value and value.strip()
    }
    language = (
        language_of(payload.question)
        if payload.language == "auto"
        else payload.language
    )

    try:
        result = rag_workflow().invoke(
            {
                "question": payload.question,
                "language": language,
                "filters": filters or None,
            }
        )
        if result.get("error"):
            raise RuntimeError(result["error"])

        return AskResponse(
            answer=result["answer"],
            language=language,
            citations=[
                chunk.citation()
                for chunk in result.get("citation_chunks", [])
            ],
        )
    except Exception as exc:
        logger.exception("RAG workflow failed")
        settings = get_settings()
        detail = (
            str(exc)
            if settings.debug
            else "RAG service is temporarily unavailable"
        )
        raise HTTPException(status_code=503, detail=detail) from exc
