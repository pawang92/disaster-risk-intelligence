from functools import lru_cache
import logging

from fastapi import FastAPI, HTTPException

from .bedrock_rag import DisasterRag
from .config import get_settings
from .ingest import language_of
from .schema import (
    AskRequest,
    AskResponse,
    HealthResponse,
    RetrievalTestRequest,
    RetrievalTestResponse,
)

app = FastAPI(
    title="Disaster Risk Intelligence RAG",
    version="0.2.0",
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def rag() -> DisasterRag:
    return DisasterRag(get_settings())


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


@app.post(
    "/v1/retrieval-test",
    response_model=RetrievalTestResponse,
)
def retrieval_test(
    payload: RetrievalTestRequest,
) -> RetrievalTestResponse:
    settings = get_settings()

    if not settings.debug:
        raise HTTPException(
            status_code=404,
            detail="Not found",
        )

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
        return RetrievalTestResponse(
            diagnostics=diagnostics,
        )
    except Exception as exc:
        logger.exception("Retrieval diagnostics failed")
        detail = (
            str(exc)
            if settings.debug
            else "Retrieval diagnostics unavailable"
        )
        raise HTTPException(
            status_code=503,
            detail=detail,
        ) from exc


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

    try:
        service = rag()
        chunks = service.retrieve(
            payload.question,
            filters or None,
        )

        if not chunks:
            return AskResponse(
                answer=(
                    "No sufficiently relevant information was found "
                    "in the indexed documents."
                ),
                language=(
                    language_of(payload.question)
                    if payload.language == "auto"
                    else payload.language
                ),
                citations=[],
            )

        language = (
            language_of(payload.question)
            if payload.language == "auto"
            else payload.language
        )

        answer = service.answer(
            payload.question,
            language,
            chunks,
        )

        return AskResponse(
            answer=answer,
            language=language,
            citations=[
                chunk.citation()
                for chunk in chunks
            ],
        )

    except Exception as exc:
        logger.exception("RAG request failed")
        settings = get_settings()
        detail = (
            str(exc)
            if settings.debug
            else "RAG service is temporarily unavailable"
        )
        raise HTTPException(
            status_code=503,
            detail=detail,
        ) from exc
