from types import SimpleNamespace

import pytest

from app.disaster_rag import DisasterRag


def make_service():
    service = object.__new__(DisasterRag)
    service.settings = SimpleNamespace(
        retrieval_k=6,
        retrieval_fallback_k=3,
        min_retrieval_score=0.2,
    )
    service.embed = lambda question, kind="query": [0.1, 0.2]
    return service


def test_filtered_query_error_does_not_retry_without_filters():
    service = make_service()
    calls = []

    def query(_embedding, _count, where=None):
        calls.append(where)
        raise ValueError("Chroma filter failure")

    service._query_collection = query

    with pytest.raises(
        RuntimeError,
        match="refusing an unfiltered search",
    ):
        service.retrieve(
            "flood evacuation guidance",
            {"district": "mumbai", "disaster_type": "flood"},
        )

    assert calls == [
        {"$and": [{"district": "mumbai"}, {"disaster_type": "flood"}]}
    ]


def test_empty_filtered_result_does_not_trigger_broad_search():
    service = make_service()
    calls = []

    def query(_embedding, _count, where=None):
        calls.append(where)
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    service._query_collection = query
    service._to_chunks = lambda _result: []

    chunks = service.retrieve(
        "flood evacuation guidance",
        {"district": "mumbai"},
    )

    assert chunks == []
    assert calls == [{"district": "mumbai"}]
