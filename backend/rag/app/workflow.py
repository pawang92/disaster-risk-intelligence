"""LangGraph orchestration for the disaster guidance RAG pipeline.

The graph deliberately keeps retrieval and generation deterministic and small:
retrieve evidence -> generate a draft -> validate every cited source/page.
"""
from __future__ import annotations

import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .disaster_rag import DisasterRag, RetrievedChunk


NO_EVIDENCE_ANSWER = (
    "I could not find sufficiently relevant evidence in the indexed "
    "disaster-guidance documents to answer this question."
)
UNVERIFIED_ANSWER = (
    "I could not verify the generated answer against the retrieved "
    "document pages. Please consult the cited official guidance directly "
    "or ask a narrower question."
)


class RAGState(TypedDict, total=False):
    question: str
    language: str
    filters: dict[str, str] | None
    chunks: list[RetrievedChunk]
    draft_answer: str
    answer: str
    citation_chunks: list[RetrievedChunk]
    error: str | None
    validation_status: str


_CITATION_PATTERN = re.compile(r"\[([^\]]+?)\s+p\.(\d+)\]")


def validate_citations(
    answer: str,
    chunks: list[RetrievedChunk],
) -> tuple[str, list[RetrievedChunk], str]:
    """Allow only citations that point to a retrieved source and page.

    This validates citation references, not the factual entailment of every
    sentence. Full claim-level grounding evaluation belongs in the evaluation
    phase and must not be implied by this check.
    """
    if not answer.strip() or not chunks:
        return NO_EVIDENCE_ANSWER, [], "abstained"

    allowed = {
        (chunk.source_key, chunk.page): chunk
        for chunk in chunks
        if chunk.source_key and chunk.page > 0
    }
    matches = list(_CITATION_PATTERN.finditer(answer))
    if not matches:
        return UNVERIFIED_ANSWER, [], "missing_citations"

    cited_keys = [(match.group(1).strip(), int(match.group(2))) for match in matches]
    if any(key not in allowed for key in cited_keys):
        return UNVERIFIED_ANSWER, [], "invalid_citations"

    # Return only source pages actually referenced in the generated answer.
    unique_keys = list(dict.fromkeys(cited_keys))
    cited_chunks = [allowed[key] for key in unique_keys]
    return answer.strip(), cited_chunks, "validated"


def build_rag_graph(service: DisasterRag):
    """Compile the retrieval -> generation -> citation-validation graph."""

    def retrieve_node(state: RAGState) -> dict[str, Any]:
        chunks = service.retrieve(
            state["question"],
            state.get("filters") or None,
        )
        return {"chunks": chunks, "error": None}

    def generate_node(state: RAGState) -> dict[str, Any]:
        chunks = state.get("chunks", [])
        if not chunks:
            return {
                "draft_answer": NO_EVIDENCE_ANSWER,
                "answer": NO_EVIDENCE_ANSWER,
                "citation_chunks": [],
                "validation_status": "abstained",
            }

        answer = service.answer(
            state["question"],
            state["language"],
            chunks,
        )
        return {"draft_answer": answer}

    def validate_node(state: RAGState) -> dict[str, Any]:
        answer, citations, status = validate_citations(
            state.get("draft_answer", ""),
            state.get("chunks", []),
        )
        return {
            "answer": answer,
            "citation_chunks": citations,
            "validation_status": status,
        }

    graph = StateGraph(RAGState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("validate_citations", validate_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "validate_citations")
    graph.add_edge("validate_citations", END)
    return graph.compile()
