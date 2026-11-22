from backend.rag.app.disaster_rag import RetrievedChunk
from backend.rag.app.workflow import (
    NO_EVIDENCE_ANSWER,
    UNVERIFIED_ANSWER,
    build_rag_graph,
    validate_citations,
)


def make_chunk(source_key="flood-guidance.pdf", page=2):
    return RetrievedChunk(
        text="Evacuate when instructed by local authorities.",
        document_id="doc-123",
        source_key=source_key,
        page=page,
        score=0.91,
        language="en",
    )


def test_validate_citations_accepts_only_retrieved_source_pages():
    chunk = make_chunk()

    answer, citations, status = validate_citations(
        "Follow the evacuation instruction [flood-guidance.pdf p.2].",
        [chunk],
    )

    assert status == "validated"
    assert answer.startswith("Follow the evacuation")
    assert citations == [chunk]


def test_validate_citations_rejects_unknown_source_page():
    answer, citations, status = validate_citations(
        "Evacuate now [unrelated.pdf p.99].",
        [make_chunk()],
    )

    assert status == "invalid_citations"
    assert answer == UNVERIFIED_ANSWER
    assert citations == []


def test_validate_citations_rejects_answer_without_citations():
    answer, citations, status = validate_citations(
        "Evacuate immediately.",
        [make_chunk()],
    )

    assert status == "missing_citations"
    assert answer == UNVERIFIED_ANSWER
    assert citations == []


def test_validate_citations_abstains_without_evidence():
    answer, citations, status = validate_citations(
        "Some generated answer.",
        [],
    )

    assert status == "abstained"
    assert answer == NO_EVIDENCE_ANSWER
    assert citations == []


def test_langgraph_pipeline_retrieves_generates_and_validates():
    chunk = make_chunk()

    class FakeRagService:
        received_filters = None

        def retrieve(self, question, filters=None):
            self.received_filters = filters
            return [chunk]

        def answer(self, question, language, chunks):
            assert language == "en"
            assert chunks == [chunk]
            return "Follow the evacuation instruction [flood-guidance.pdf p.2]."

    service = FakeRagService()
    graph = build_rag_graph(service)

    result = graph.invoke(
        {
            "question": "What is the evacuation guidance?",
            "language": "en",
            "filters": {"district": "mumbai", "disaster_type": "flood"},
        }
    )

    assert service.received_filters == {
        "district": "mumbai",
        "disaster_type": "flood",
    }
    assert result["validation_status"] == "validated"
    assert result["citation_chunks"] == [chunk]
    assert result["answer"].endswith("[flood-guidance.pdf p.2].")


def test_langgraph_pipeline_abstains_when_retrieval_is_empty():
    class EmptyRagService:
        def retrieve(self, question, filters=None):
            return []

        def answer(self, question, language, chunks):
            raise AssertionError("Generation must not run without evidence.")

    graph = build_rag_graph(EmptyRagService())
    result = graph.invoke(
        {
            "question": "What is the flood guidance?",
            "language": "en",
            "filters": None,
        }
    )

    assert result["validation_status"] == "abstained"
    assert result["answer"] == NO_EVIDENCE_ANSWER
    assert result["citation_chunks"] == []
